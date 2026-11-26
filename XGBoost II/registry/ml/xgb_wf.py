# -*- coding: utf-8 -*-
"""XGB_WF_01: обучение XGBoost по скользящим окнам и прогнозы на проверочных месяцах разработки.
Правила записаны в registry/specs/XGB_WF_01.md и XGB_WF_02.md: правило, срок сделки и стоп берутся из конфига. Читаются только бары и столбцы до 2025-01-01.

Использование: python xgb_wf.py <тестер> <конфиг ml/configs/xgb_XXX_H1.json> <папка баз> <папка столбцов> <папка вывода>
Печатает строку вида RESULT {...}. Код выхода 0 только если все проверки пройдены.
"""
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import xgboost as xgb

HERE = Path(__file__).resolve().parent
REG = HERE.parent
sys.path.insert(0, str(REG / "tests"))
import xcheck_common as X

RULES = ("XGB_WF_01", "XGB_WF_02")
NCOLS = 82
DROP = (7, 28, 79, 80)                       # повторы и постоянный столбец на H1
USE = [i for i in range(NCOLS) if i not in DROP]


def load_features(path):
    """Таблица EQIND001: времена баров и n x 82."""
    data = Path(path).read_bytes()
    magic, _, ncols, n = struct.unpack_from("<8siiq", data)
    if magic != b"EQIND001" or ncols != NCOLS or len(data) != 64 + 8 * n + 4 * n * ncols:
        raise SystemExit(f"STOP: испорченный файл столбцов {path}")
    t = np.frombuffer(data, dtype="<i8", count=n, offset=64)
    f = np.frombuffer(data, dtype="<f4", count=n * ncols, offset=64 + 8 * n).reshape(ncols, n).T
    return t.copy(), f.copy()


def atr14(B):
    h, l, c = (np.array(B[k], dtype=float) for k in ("H", "L", "C"))
    tr = h - l
    tr[1:] = np.maximum(tr[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    a = np.full(len(c), np.nan)
    for i in range(13, len(c)):
        a[i] = tr[i - 13:i + 1].sum() / 14
    return a


def labels(B, pair, hold, mult):
    """Для каждого бара сигнала i и каждой стороны: результат сделки в R и в цене, номер бара выхода."""
    O, H, L, C, SP, pt = B["O"], B["H"], B["L"], B["C"], B["SP"], B["pt"]
    n = len(C)
    A = atr14(B)
    lot = 100 if pair.startswith("XAU") else 100000
    R = np.full((n, 2), np.nan)
    pnl = np.full((n, 2), np.nan)
    out = np.full((n, 2), -1, dtype=np.int64)
    for i in range(n):
        e = i + 1
        if e + hold - 1 >= n or not A[i] > 0:
            continue
        dist = mult * A[i]
        for side, d in enumerate((1, -1)):
            entry = O[e] + SP[e] * pt if d > 0 else O[e]
            stop = entry - d * dist
            price = None
            for k in range(e, e + hold):
                add = 0 if d > 0 else SP[k] * pt
                first, worst = O[k] + add, (L[k] if d > 0 else H[k] + add)
                if k > e and d * (first - stop) <= 0:
                    price = first
                    break
                if d * (worst - stop) <= 0:
                    price = stop
                    break
            if price is None:
                k = e + hold - 1
                price = C[k] if d > 0 else C[k] + SP[k] * pt
            comm = 7 / lot * (1 if pair.endswith("USD") else entry)
            pnl[i, side] = d * (price - entry) - comm
            R[i, side] = pnl[i, side] / dist
            out[i, side] = k
    return R, pnl, out


def nights_between(entry_time, exit_bar_time):
    """Сколько раз сменилась дата UTC между баром входа и баром выхода (выходные входят в счёт)."""
    return int(exit_bar_time) // 86400 - int(entry_time) // 86400


def fit(F, y, P):
    params = {"objective": "reg:squarederror", "max_depth": int(P["max_depth"]), "eta": P["learning_rate"],
              "subsample": P["subsample"], "colsample_bytree": P["colsample_bytree"],
              "min_child_weight": P["min_child_weight"], "lambda": P["reg_lambda"], "seed": int(P["seed"]),
              "nthread": 1, "tree_method": "hist"}
    return xgb.train(params, xgb.DMatrix(F, label=y), num_boost_round=int(P["rounds"]))


def train_predict(F, R, T, train0, idx0, rows, P, hold):
    """Две модели на примерах обучающего отрезка, прогнозы для строк rows. idx0 - первый бар проверки."""
    n = len(T)
    ok = (T >= train0) & (np.arange(n) + hold < idx0) & np.isfinite(R[:, 0]) & np.isfinite(R[:, 1])
    train = np.nonzero(ok)[0]
    assert len(train) > 500 and train.max() + hold < idx0, "обучающие примеры заходят в проверку"
    models = [fit(F[train], R[train, side], P) for side in (0, 1)]
    pred = np.column_stack([m.predict(xgb.DMatrix(F[rows])) for m in models])
    return models, pred, len(train)


def main(tester, cfg_path, base, ind, work):
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8-sig"))
    reg = json.loads((REG / "rules_registry.json").read_text(encoding="utf-8-sig"))
    enabled = [k for k, v in cfg["rules"].items() if v.get("enabled") and k in RULES]
    if len(enabled) != 1:
        raise SystemExit("STOP: в конфиге должно быть включено ровно одно правило модели")
    rid = enabled[0]
    rule = next(r for r in reg["rules"] if r["id"] == rid)
    P = {k: v["default"] for k, v in rule["params"].items()}
    P.update(cfg["rules"][rid].get("params", {}))
    pair, name = cfg["data"]["pair"], cfg["test_name"]
    hold, mult = int(cfg["exits"]["hold_bars"]), float(cfg["exits"]["stop_atr_mult"])
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)

    B = X.load(str(Path(base) / pair / f"{pair}_H1.bin"), X.DEV_CUT)
    T = np.array(B["T"], dtype=np.int64)
    n = len(T)
    ft, F = load_features(Path(ind) / pair / f"{pair}_H1_dev.bin")
    if len(ft) != n or not np.array_equal(ft, T):
        raise SystemExit(f"STOP: времена столбцов и баров не совпадают ({len(ft)} и {n})")
    F = F[:, USE]
    R, pnl, out = labels(B, pair, hold, mult)

    sig = np.zeros(n, dtype=int)
    leak = 0
    windows = X.dev_windows(B["T"][0])
    for num, t0, t1 in windows:
        train0 = X.month(2020, 1, 2 * (num - 1))
        idx0, idx1 = int(np.searchsorted(T, t0)), int(np.searchsorted(T, t1))
        rows = np.arange(idx0 - 1, idx1 - 1)                  # вход по открытию следующего бара попадает в окно
        models, pred, ntrain = train_predict(F, R, T, train0, idx0, rows, P, hold)
        long_ok = (pred[:, 0] >= P["threshold_R"]) & (pred[:, 0] >= pred[:, 1])
        short_ok = (pred[:, 1] >= P["threshold_R"]) & (pred[:, 1] > pred[:, 0])
        sig[rows] = np.where(long_ok, 1, np.where(short_ok, -1, 0))

        # причинность: всё с первого проверочного бара заменено мусором, модель обучается заново
        rng = np.random.default_rng(num)
        bad = {k: (list(v) if isinstance(v, list) else v) for k, v in B.items()}
        for k, scale in (("O", 1.37), ("H", 1.41), ("L", 0.63), ("C", 0.77)):
            bad[k][idx0:] = [x * scale for x in bad[k][idx0:]]
        bad["SP"][idx0:] = [x * 3 + 7 for x in bad["SP"][idx0:]]
        F2 = F.copy()
        F2[idx0:] = rng.normal(size=F2[idx0:].shape)
        R2 = labels(bad, pair, hold, mult)[0]
        models2, _, ntrain2 = train_predict(F2, R2, T, train0, idx0, rows, P, hold)
        again = np.column_stack([m.predict(xgb.DMatrix(F[rows])) for m in models2])
        same = ntrain == ntrain2 and np.array_equal(again, pred)
        leak += not same
        print(f"{pair} окно {num}: примеров {ntrain}, входных сигналов {int(np.count_nonzero(sig[rows]))}, "
              f"причинность {'OK' if same else 'НАРУШЕНА'}", flush=True)

    sig_path = work / f"{name}_signals.csv"
    with open(sig_path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("time,signal\n")
        for i in np.nonzero(sig)[0]:
            fh.write(f"{T[i]},{sig[i]}\n")

    run_cfg = dict(cfg)
    run_cfg["data"] = dict(cfg["data"], bars_dir=str(Path(base).resolve()))
    run_cfg["output"] = str(work / f"{name}.json")
    run_cfg["registry"] = str(REG / "rules_registry.json")
    c2 = work / f"{name}_config.json"
    c2.write_text(json.dumps(run_cfg, ensure_ascii=False), encoding="utf-8")
    Path(run_cfg["output"]).unlink(missing_ok=True)
    r = subprocess.run([str(tester), str(c2), "--selftest", f"--signals={sig_path}"])
    if r.returncode:
        raise SystemExit(f"STOP: тестер завершился с кодом {r.returncode}")
    res = json.loads(Path(run_cfg["output"]).read_text(encoding="utf-8"))

    # сверка 1: сделки из тех же результатов, на которых училась модель; сверка 2: общий расчёт проверок
    start = int(np.searchsorted(T, windows[0][1]))
    mine, free, nights = [], 0, 0
    for x in np.nonzero(sig)[0]:
        if x + 1 < start or x < free:
            continue
        side = 0 if sig[x] > 0 else 1
        if out[x, side] < 0:
            if x + hold >= n:
                break
            continue
        mine.append((int(T[x + 1]), float(pnl[x, side]) / (10 * B["pt"])))
        free = int(out[x, side])
        nights += nights_between(T[x + 1], T[free])
    print("сверка с примерами обучения:")
    bad = X.compare(res, mine, B["T"][0])
    print("сверка с общим расчётом сделок:")
    bad += X.compare(res, X.trades(B, [int(v) for v in sig], pair, windows[0][1], hold, mult), B["T"][0])

    seg = res["rules"][0]["segments"][0]
    summary = {"pair": pair, "test": name, "trades": seg["trades"], "win_pct": seg["win_pct"], "net_pips": seg["net_pips"],
               "profit_factor": seg["profit_factor"], "avg_R": seg["avg_R"], "max_dd_pips": seg["max_dd_pips"],
               "pos_windows": seg["pos_windows"], "verdict": res["rules"][0]["verdict"],
               "nights_per_trade": nights / max(len(mine), 1),
               "net_pips_per_night": sum(p for _, p in mine) / nights if nights else None,
               "rule": rid, "mismatch": int(bad), "leak_windows": int(leak), "xgboost": xgb.__version__}
    print("RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if bad or leak else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main(*sys.argv[1:6]))
