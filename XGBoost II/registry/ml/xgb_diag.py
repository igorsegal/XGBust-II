# -*- coding: utf-8 -*-
"""XGB_DIAG_01: есть ли сигнал у модели (XGB_WF_01, XGB_WF_02) без расходов и лучше ли он случайных входов.
Правила записаны в registry/specs/XGB_DIAG_01.md (для XGB_WF_02 - с отличием из XGB_WF_02.md). Берёт готовые сигналы из прогона xgb_wf.py, ничего не переобучает.
Читаются только бары до 2025-01-01.

Использование: python xgb_diag.py <тестер> <конфиг ml/configs/xgb_XXX_H1.json> <папка баз> <папка вывода xgb_wf> <папка вывода>
Печатает строку вида RESULT {...}. Код выхода 0 только если все проверки пройдены.
"""
import json
import struct
import subprocess
import sys
from bisect import bisect_left
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REG = HERE.parent
sys.path.insert(0, str(REG / "tests"))
sys.path.insert(0, str(HERE))
import xcheck_common as X
from xgb_wf import atr14, labels

PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD")
SEED = 20261125
REPS = 1000
CONTROL_REPS = 200
# правило: (наименьший сдвиг от начала и конца отрезка, баров; порог p) - записано в его описании до прогона
NULL = {"XGB_WF_01": (24, 0.05), "XGB_WF_02": (0, 0.025)}
NWIN = 27


def simulate(idx, side, out, start, hold):
    """Сделки по сигналам: idx - номера баров сигнала по возрастанию, side - 0 покупка, 1 продажа.
    Одна позиция: следующий сигнал берётся не раньше бара выхода. Возвращает пары (бар, сторона)."""
    n = len(out)
    taken = []
    k = bisect_left(idx, start - 1)
    while k < len(idx):
        x, s = idx[k], side[k]
        e = out[x][s]
        if e < 0:
            if x + hold >= n:
                break
            k += 1
            continue
        taken.append((x, s))
        k = bisect_left(idx, e, k + 1)
    return taken


def shifted(sig, segments, fractions, edge):
    """Сдвиг ряда сигналов по кругу внутри каждого отрезка [a, b); доля 0..1 задаёт величину сдвига,
    edge - наименьший сдвиг от начала и от конца отрезка, баров."""
    new = sig.copy()
    for (a, b), u in zip(segments, fractions):
        length = b - a
        if length <= 2 * edge:
            continue
        off = edge + int(u * (length - 2 * edge + 1))
        new[a:b] = np.roll(sig[a:b], off)
    return new


def run_signals(sig, out, start, hold):
    idx = np.nonzero(sig)[0]
    return simulate(idx.tolist(), np.where(sig[idx] > 0, 0, 1).tolist(), out, start, hold)


def null_runs(sig, segments, fractions, R, out, start, hold, edge):
    """Для каждого варианта сдвига: сумма R и число сделок."""
    total, count = [], []
    for row in fractions:
        taken = run_signals(shifted(sig, segments, row, edge), out, start, hold)
        total.append(sum(R[x][s] for x, s in taken))
        count.append(len(taken))
    return total, count


def zero_spread_copy(src, dst):
    """Копия файла баров с нулевым спредом (для сверки с тестером)."""
    data = bytearray(Path(src).read_bytes())
    n, = struct.unpack_from("<q", data, 32)
    sl, = struct.unpack_from("<i", data, 56)
    off = 60 + sl
    assert len(data) >= off + 60 * n
    for i in range(n):
        data[off + 60 * i + 48:off + 60 * i + 52] = b"\0\0\0\0"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(data))


def main(tester, cfg_path, base, mldir, work):
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8-sig"))
    pair, name = cfg["data"]["pair"], cfg["test_name"]
    hold, mult = int(cfg["exits"]["hold_bars"]), float(cfg["exits"]["stop_atr_mult"])
    rid, = [k for k, v in cfg["rules"].items() if v.get("enabled")]
    edge, p_limit = NULL[rid]
    mldir, work = Path(mldir).resolve(), Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    bars = Path(base).resolve() / pair / f"{pair}_H1.bin"

    B = X.load(str(bars), X.DEV_CUT)
    T = B["T"]
    n = len(T)
    pt = B["pt"]
    where = {t: i for i, t in enumerate(T)}
    sig = np.zeros(n, dtype=int)
    for line in (mldir / f"{name}_signals.csv").read_text(encoding="ascii").split()[1:]:
        t, s = line.split(",")
        sig[where[int(t)]] = int(s)

    windows = X.dev_windows(T[0])
    segments, nums = [], []
    for num, t0, t1 in windows:
        segments.append((int(np.searchsorted(T, t0)) - 1, int(np.searchsorted(T, t1)) - 1))
        nums.append(num)
    start = segments[0][0] + 1
    outside = sig.copy()
    for a, b in segments:
        outside[a:b] = 0
    assert not outside.any(), "сигналы вне проверочных отрезков"

    # с расходами: должно совпасть с тестером
    _, pnl, out = labels(B, pair, hold, mult)
    out_l = out.tolist()
    net = [(T[x + 1], float(pnl[x, s]) / (10 * pt)) for x, s in run_signals(sig, out_l, start, hold)]
    # спред и комиссия, заплаченные в этих же сделках: у покупки спред бара входа, у продажи - бара выхода
    paid = []
    for x, s in run_signals(sig, out_l, start, hold):
        spread = B["SP"][x + 1 if s == 0 else int(out[x, s])] * pt
        comm1 = 7 / (100 if pair.startswith("XAU") else 100000) * (1 if pair.endswith("USD") else B["O"][x + 1] + (spread if s == 0 else 0))
        paid.append((spread + comm1) / (10 * pt))
    res_net = json.loads((mldir / f"{name}.json").read_text(encoding="utf-8"))
    print("сверка с тестером, с расходами:")
    bad = X.compare(res_net, net, T[0])

    # без расходов: спред ноль, комиссия возвращается в результат
    B0 = dict(B, SP=[0] * n)
    _, pnl0, out0 = labels(B0, pair, hold, mult)
    A = atr14(B)
    lot = 100 if pair.startswith("XAU") else 100000
    opens = np.array(B["O"], dtype=float)
    entry = np.append(opens[1:], np.nan)
    comm = 7 / lot * (np.ones(n) if pair.endswith("USD") else entry)
    gpnl = pnl0 + comm[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        gR = gpnl / (mult * A)[:, None]
    out0_l, gR_l = out0.tolist(), gR.tolist()
    taken = run_signals(sig, out0_l, start, hold)
    gross = [(T[x + 1], float(gpnl[x, s]) / (10 * pt)) for x, s in taken]

    zero = work / "zero"
    zero_spread_copy(bars, zero / pair / f"{pair}_H1.bin")
    run_cfg = dict(cfg)
    run_cfg["data"] = dict(cfg["data"], bars_dir=str(zero))
    run_cfg["costs"] = dict(cfg["costs"], commission_per_lot_usd=0)
    run_cfg["output"] = str(work / f"{name}_gross.json")
    run_cfg["registry"] = str(REG / "rules_registry.json")
    c2 = work / f"{name}_gross_config.json"
    c2.write_text(json.dumps(run_cfg, ensure_ascii=False), encoding="utf-8")
    Path(run_cfg["output"]).unlink(missing_ok=True)
    r = subprocess.run([str(tester), str(c2), "--selftest", f"--signals={mldir / (name + '_signals.csv')}"])
    if r.returncode:
        raise SystemExit(f"STOP: тестер завершился с кодом {r.returncode}")
    print("сверка с тестером, без расходов:")
    bad += X.compare(json.loads(Path(run_cfg["output"]).read_text(encoding="utf-8")), gross, T[0])

    # случайные сдвиги: одна и та же доля для всех инструментов в одном окне и варианте
    rng = np.random.default_rng(SEED)
    u_win = rng.random((REPS, NWIN))
    u_all = rng.random((REPS, 1))
    within = null_runs(sig, segments, u_win[:, [k - 1 for k in nums]], gR_l, out0_l, start, hold, edge)
    whole = null_runs(sig, [(segments[0][0], segments[-1][1])], u_all, gR_l, out0_l, start, hold, edge)

    # проверка самого разбора: сигналы, знающие будущее, обязаны быть лучше всех сдвинутых
    rows = np.arange(segments[0][0], segments[-1][1])
    pick = rows[np.random.default_rng(1).random(len(rows)) < 0.1]
    pick = pick[np.isfinite(gR[pick]).all(axis=1) & (np.nan_to_num(gR[pick]).max(axis=1) > 0)]
    cheat = np.zeros(n, dtype=int)
    cheat[pick] = np.where(gR[pick, 0] >= gR[pick, 1], 1, -1)
    ct = run_signals(cheat, out0_l, start, hold)
    cheat_mean = sum(gR_l[x][s] for x, s in ct) / len(ct)
    cs, cn = null_runs(cheat, segments, u_win[:CONTROL_REPS, [k - 1 for k in nums]], gR_l, out0_l, start, hold, edge)
    control = int(all(a / b < cheat_mean for a, b in zip(cs, cn)))
    print(f"подставные сигналы с заглядыванием в будущее: {'лучше всех случайных, OK' if control else 'НЕ ВЫДЕЛЯЮТСЯ'}")

    detail = {"pair": pair, "rule": rid, "p_limit": p_limit, "trades": len(taken), "sum_R": sum(gR_l[x][s] for x, s in taken),
              "gross_pips": sum(p for _, p in gross), "net_trades": len(net), "net_pips": sum(p for _, p in net), "cost_pips": sum(paid),
              "long_share": sum(s == 0 for _, s in taken) / max(len(taken), 1),
              "within": {"sum_R": within[0], "n": within[1]}, "whole": {"sum_R": whole[0], "n": whole[1]},
              "mismatch": int(bad), "control_ok": control}
    (work / f"{name}_diag.json").write_text(json.dumps(detail), encoding="utf-8")
    short = {k: v for k, v in detail.items() if k not in ("within", "whole")}
    print("RESULT " + json.dumps(short, ensure_ascii=False), flush=True)
    return 1 if bad or not control else 0


def compare_null(items, key):
    """items - разборы инструментов. Средний R модели, медиана случайных, их доля ниже модели, p."""
    n = sum(d["trades"] for d in items)
    model = sum(d["sum_R"] for d in items) / n
    total = np.sum([d[key]["sum_R"] for d in items], axis=0)
    count = np.sum([d[key]["n"] for d in items], axis=0)
    rand = total / count
    better = int(np.sum(rand >= model))
    return {"trades": n, "mean_R": model, "random_median_R": float(np.median(rand)),
            "below_pct": 100.0 * float(np.mean(rand < model)), "p": (1 + better) / (1 + len(rand))}


def report(items):
    """Строки раздела отчёта по всем инструментам."""
    lines = ["| Инструмент | Сделок без расходов | Пунктов на сделку: с расходами | без расходов | спред и комиссия "
             "| R на сделку без расходов | Случайные, середина | Случайных хуже модели, % |", "|" + "---|" * 8]
    for d in items:
        c = compare_null([d], "within")
        lines.append(f"| {d['pair']} | {d['trades']} | {d['net_pips'] / d['net_trades']:.2f} "
                     f"| {d['gross_pips'] / d['trades']:.2f} | {d['cost_pips'] / d['net_trades']:.2f} "
                     f"| {c['mean_R']:.4f} | {c['random_median_R']:.4f} "
                     f"| {c['below_pct']:.1f} |")
    if len(items) != len(PAIRS):
        return lines + ["", "**Вывод не сделан: разобраны не все инструменты.**", ""]
    main_c, extra = compare_null(items, "within"), compare_null(items, "whole")
    limit = items[0]["p_limit"]
    found = main_c["mean_R"] > 0 and main_c["p"] <= limit
    lines += ["", f"Все пять вместе: сделок {main_c['trades']}, средний результат без расходов {main_c['mean_R']:.4f} R, "
              f"середина случайных {main_c['random_median_R']:.4f} R, случайных хуже модели {main_c['below_pct']:.1f} %, "
              f"p = {main_c['p']:.4f} (порог {limit}).", "",
              f"Для сведения, сдвиг по всему периоду: середина случайных {extra['random_median_R']:.4f} R, "
              f"случайных хуже модели {extra['below_pct']:.1f} %, p = {extra['p']:.4f}.", "",
              "**Вывод по записанному критерию: " + ("сигнал есть" if found else "сигнал от случая не отличим") + ".**", ""]
    return lines


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main(*sys.argv[1:6]))
