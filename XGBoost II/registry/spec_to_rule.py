#!/usr/bin/env python3
"""spec_to_rule.py - одобренная жюри спека -> черновик правила-условия (без кода на C++) -> проверки.

Порядок: модель переводит спеку в запись реестра (inputs и строка условия) -> validate_registry.py ->
вторая роль сверяет правило со спекой -> tester --selftest (заглядывание в будущее) на разработке.
Ошибки проверок возвращаются модели, всего до 3 попыток. Торговые результаты модели НЕ показываются.
Экзамен не открывается никогда. rules_registry.json не изменяется: черновики кладутся в data_test/drafts.

Запуск из корня проекта:
  python registry/spec_to_rule.py --tester путь\\tester.exe [--specs data\\specs] [--out data_test\\drafts]
                                  [--bars D:\\AHexaTrader\\1DataFiles\\BAZA] [--again]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from src import jury  # noqa: E402

ATTEMPTS = 3
PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD")  # решение от 2026-11-25
PERIOD = {"train_months": 6, "test_months": 2, "step_months": 2,
          "dev_from": "2020-01", "exam_from": "2025-01", "exam_to": "2026-04"}
INPUT_KEYS = ("name", "indicator", "output", "tf", "source", "params")
PARAM_KEYS = ("type", "default", "min", "max", "note")

jury.OTHER_ROLES["translator"] = (
    "Ты переводишь описание торгового правила (SPEC) в запись для тестера. Тестер умеет только сравнения "
    "индикаторов из CATALOG, цен open high low close spread, чисел и параметров; операции + - * /, "
    "< <= > >= == !=, AND OR NOT, скобки и функции abs(x) min(a,b) max(a,b) prev(x,n) crossup(a,b) crossdown(a,b). "
    "Цепочки a < b < c запрещены. Условие вычисляется на закрытии бара, вход на следующем. Старший таймфрейм "
    "берётся по последнему закрытому бару. Переведи ТОЧНО. Если хоть одна обязательная часть условия входа этими "
    "средствами не выражается (своя формула, обучаемая модель, веса, состояние между барами, отсутствующий "
    "индикатор), не приближай и не заменяй похожим: верни expressible=false. Выход и стоп не переводи: их задаёт "
    "тестер. Ответ только JSON с ключами: expressible (true или false), reason (почему нет), missing (список того, "
    "чего не хватает), name, direction (both, long или short), timeframes (список из CATALOG), pairs (список), "
    "params (словарь имя: {type int или float, default, min, max, note}), inputs (список объектов name, indicator, "
    "output, tf, source, params; значение параметра - число или строка '$имя_параметра'), entry_long_expr, "
    "entry_short_expr, assumptions (список всех допущений, которых нет в SPEC)."
)
jury.OTHER_ROLES["checker"] = (
    "Ты придирчивый проверяющий. Сравни описание правила SPEC и его запись для тестера RULE. Ищи расхождения в "
    "условии входа: направление, знак сравнения, порядок величин, сдвиг бара, таймфрейм, значения параметров, "
    "пропущенное или лишнее условие, замена индикатора похожим. Выход и стоп не проверяй. Нынешний бар в RULE "
    "означает уже закрытый бар. Ответ только JSON с ключами: matches (true или false), differences (список "
    "расхождений, по одной фразе; пустой, если их нет)."
)
jury.MAX_TOKENS.update({"translator": 3000, "checker": 1500})


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def article_id(url: str) -> str:
    m = re.search(r"/articles/(\d+)", url or "")
    return m.group(1) if m else ""


def in_registry(reg, url: str) -> str:
    """id правила реестра из той же статьи или пустая строка."""
    num = article_id(url)
    for r in reg.get("rules", []):
        src = r.get("source") or {}
        if num and (str(src.get("article_id")) == num or article_id(str(src.get("url", ""))) == num):
            return r["id"]
    return ""


def catalog_text(cat) -> str:
    lines = ["timeframes: " + " ".join(cat["timeframes"]), "sources: " + " ".join(cat["sources"])]
    for i in cat["indicators"]:
        if i.get("status") != "implemented":
            continue
        ps = ", ".join(f"{k}={v['default']} [{v['min']}..{v['max']}]" for k, v in i.get("params", {}).items())
        lines.append(f"{i['id']}: выходы {','.join(i['outputs'])}; параметры {ps or 'нет'}; {i.get('formula', '')[:160]}")
    return "\n".join(lines)


def build_entry(answer: dict, spec: dict, rid: str, cat: dict) -> dict:
    """Запись реестра. Всё служебное заполняет программа; из ответа модели берутся только разрешённые поля."""
    params = {}
    for k, p in (answer.get("params") or {}).items():
        params[str(k)] = {x: p[x] for x in PARAM_KEYS if isinstance(p, dict) and x in p}
    inputs = [{k: i[k] for k in INPUT_KEYS if k in i and i[k] not in (None, "")}
              for i in answer.get("inputs") or [] if isinstance(i, dict)]
    tfs = [t for t in answer.get("timeframes") or [] if t in cat["timeframes"]] or ["H1"]
    pairs = [p for p in answer.get("pairs") or [] if p in PAIRS] or ["EURUSD"]
    entry = {
        "id": rid, "name": str(answer.get("name") or spec.get("title") or rid)[:160],
        "source": {"type": "article", "article_id": int(article_id(spec.get("url")) or 0), "url": spec.get("url", ""),
                   "title": spec.get("title", ""), "year": spec.get("published_year"), "spec_file": spec.get("_file", "")},
        "status": "spec_ready", "enabled_by_default": False,
        "direction": answer.get("direction") if answer.get("direction") in ("both", "long", "short") else "both",
        "timeframes": tfs, "pairs": pairs,
        "entry_long": str(spec.get("entry_long") or ""), "entry_short": str(spec.get("entry_short") or ""),
        "exit_rule": "общий выход тестера: через 24 бара", "stop_rule": "общий стоп тестера: 2 ATR(14)",
        "description": str(spec.get("summary") or ""), "params": params,
        "assumptions": [str(a) for a in answer.get("assumptions") or []],
        "implementation": {"kind": "expr"},
        "audit": {"lookahead": "unchecked", "duplicate_of": None, "constitution_ok": True,
                  "notes": ["черновик spec_to_rule.py, переведён моделью"]},
        "results": [], "inputs": inputs,
    }
    for k in ("entry_long_expr", "entry_short_expr"):
        if str(answer.get(k) or "").strip():
            entry[k] = str(answer[k]).strip()
    return entry


def make_config(rid, pair, tf, bars, reg_path, out_path):
    return {"test_name": f"draft_{rid}_{pair}_{tf}", "data": {"bars_dir": bars, "pair": pair, "timeframe": tf},
            "period": PERIOD, "costs": {"commission_per_lot_usd": 7},
            "exits": {"hold_bars": 24, "stop_atr_mult": 2.0, "atr_period": 14},
            "criteria": {"min_trades": 100, "min_profit_factor": 1.3},
            "rules": {rid: {"enabled": True, "params": {}}}, "role": "draft",
            "registry": reg_path, "catalog": os.path.join(HERE, "indicators_catalog.json"), "output": out_path}


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, timeout=900, env={**os.environ, "PYTHONUTF8": "1"})
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


class EnvError(RuntimeError):
    """Сбой окружения (нет баров, тестера): модели его не отдаём."""


def check_rule(entry, reg, args, work_reg, work_cfg):
    """(список ошибок для модели, результаты разработки). Пишет только временные файлы и results."""
    rid, tf = entry["id"], entry["timeframes"][0]
    save(work_reg, {**reg, "rules": reg["rules"] + [entry]})
    save(work_cfg, make_config(rid, "EURUSD", tf, args.bars, work_reg, os.path.join(args.out, "results", "x.json")))
    code, text = run_cmd([sys.executable, os.path.join(HERE, "validate_registry.py"), work_reg, work_cfg])
    if code:
        errs = [ln for ln in text.splitlines() if ln.startswith("ОШИБКА") and (rid in ln or "draft" in ln)]
        if not errs:
            raise EnvError("проверка реестра не прошла не из-за черновика: " + text[-600:])
        return errs, []
    dev = []
    os.makedirs(os.path.join(args.out, "results"), exist_ok=True)
    for pair in PAIRS:
        if not os.path.exists(os.path.join(args.bars, pair, f"{pair}_{tf}.bin")):
            dev.append({"pair": pair, "note": "нет файла баров"})
            continue
        out = os.path.join(os.path.abspath(args.out), "results", f"{rid}_{pair}_{tf}.json")
        save(work_cfg, make_config(rid, pair, tf, args.bars, work_reg, out))
        code, text = run_cmd([args.tester, work_cfg, "--selftest"])  # ключ --exam здесь не передаётся никогда
        if code == 4:
            return ["тестер: ЕСТЬ ЗАГЛЯДЫВАНИЕ В БУДУЩЕЕ (сигналы или индикаторы меняются от будущих баров)"], []
        if code:
            lines = [ln for ln in text.splitlines() if ln.startswith("ОШИБКА")]
            if any("файл" in ln or "данных" in ln for ln in lines) or not lines:
                raise EnvError(f"тестер, {pair}: код {code}: {text[-600:]}")
            return ["тестер: " + ln for ln in lines], []
        seg = load(out)["rules"][0]
        s = seg["segments"][0]
        dev.append({"pair": pair, "trades": s["trades"], "net_pips": s["net_pips"], "profit_factor": s["profit_factor"],
                    "pos_windows": s["pos_windows"], "verdict": seg["verdict"]})
    if not any("trades" in d for d in dev):
        raise EnvError(f"нет файлов баров {tf} в {args.bars}")
    return [], dev


def convert(spec, reg, cat, client, model, args) -> dict:
    num = article_id(spec.get("url")) or os.path.splitext(spec["_file"])[0]
    rid = "ART_" + re.sub(r"[^A-Z0-9_]", "_", num.upper()) + "_01"
    trace = {"path": os.path.join(args.out, "raw", rid + ".jsonl"), "run": time.strftime("%Y%m%d-%H%M%S")}
    brief = {k: spec.get(k) for k in ("title", "formula_and_logic", "entry_long", "entry_short", "parameters",
                                      "timeframes", "forex_pairs", "source_quotes") if spec.get(k)}
    ask = f"SPEC: {json.dumps(brief, ensure_ascii=False)}\n\nCATALOG:\n{catalog_text(cat)}"
    history, remark = [], ""
    work_reg = os.path.join(HERE, "_draft_registry.json")
    work_cfg = os.path.join(HERE, "_draft_config.json")
    try:
        for n in range(1, ATTEMPTS + 1):
            ans = jury._ask_retry(client, model, "translator", ask + remark, trace)
            if ans.get("expressible") is not True:
                return {"id": rid, "status": "нужен код", "reason": ans.get("reason"), "missing": ans.get("missing"),
                        "attempts": history}
            entry = build_entry(ans, spec, rid, cat)
            dev = []
            check = jury._ask_retry(client, model, "checker", "SPEC: " + json.dumps(brief, ensure_ascii=False)
                                    + "\n\nRULE: " + json.dumps({k: entry.get(k) for k in (
                                        "direction", "timeframes", "params", "inputs", "entry_long_expr",
                                        "entry_short_expr", "assumptions")}, ensure_ascii=False), trace)
            if check.get("matches") is True:
                errors, dev = check_rule(entry, reg, args, work_reg, work_cfg)
            else:  # правило не то, что в спеке: на истории его не считаем
                errors = ["расхождение со SPEC: " + str(x) for x in check.get("differences") or ["не названо"]]
            history.append({"attempt": n, "errors": errors})
            if not errors:
                entry["status"] = "implemented_untested"
                entry["audit"]["lookahead"] = "checked by tester selftest"
                return {"id": rid, "status": "проверено", "rule": entry, "attempts": history, "development": dev}
            remark = ("\n\nТВОЙ ПРОШЛЫЙ ОТВЕТ: " + json.dumps(ans, ensure_ascii=False)
                      + "\nОШИБКИ ПРОВЕРКИ: " + "; ".join(errors)[:2000] + "\nИсправь и дай ответ целиком. Если без "
                      "приближений исправить нельзя, верни expressible=false.")
        return {"id": rid, "status": "не прошло проверки", "attempts": history}
    finally:
        for f in (work_reg, work_cfg):
            if os.path.exists(f):
                os.remove(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--specs", default=os.path.join(ROOT, "data", "specs"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data_test", "drafts"))
    ap.add_argument("--bars", default="D:\\AHexaTrader\\1DataFiles\\BAZA")
    ap.add_argument("--tester", default=os.path.join(HERE, "tester", "tester.exe"))
    ap.add_argument("--again", action="store_true", help="переделать и те, по которым черновик уже есть")
    args = ap.parse_args(argv)
    args.out, args.tester, args.bars = (os.path.abspath(x) for x in (args.out, args.tester, args.bars))
    os.makedirs(args.out, exist_ok=True)
    jury.DATA_DIR, jury.LOG_PATH = args.out, os.path.join(args.out, "log.txt")  # журнал жюри не трогаем
    if not os.path.exists(args.tester):
        print("Нет тестера:", args.tester)
        return 2
    files = sorted(glob.glob(os.path.join(args.specs, "*.json")))
    reg = load(os.path.join(HERE, "rules_registry.json"))
    cat = load(os.path.join(HERE, "indicators_catalog.json"))
    cl = jury._client()
    if cl is None:
        print("Нет ключа жюри")
        return 2
    client, model, _ = cl
    summary = [f"spec_to_rule {time.strftime('%Y-%m-%d %H:%M:%S')}, модель {model}, спек: {len(files)}. "
               "Торговые числа - только разработка 2020-2024, экзамен закрыт."]
    bad = 0
    for f in files:
        spec = load(f)
        spec["_file"] = os.path.basename(f)
        name, done = spec["_file"], os.path.join(args.out, os.path.splitext(spec["_file"])[0] + ".json")
        if spec.get("edge_type") == "Feature_Or_Filter":
            line = f"{name}: признак или фильтр, в правило входа не переводится"
        elif in_registry(reg, spec.get("url")):
            line = f"{name}: уже есть в реестре как {in_registry(reg, spec.get('url'))}"
        elif os.path.exists(done) and not args.again:
            line = f"{name}: черновик уже есть ({load(done).get('status')})"
        else:
            try:
                res = convert(spec, reg, cat, client, model, args)
                save(done, res)
                line = f"{name}: {res['status']}"
                if res["status"] == "нужен код":
                    line += f" - {res.get('reason')}"
                for d in res.get("development", []):
                    line += (f"\n    {d['pair']}: сделок {d['trades']}, нетто {d['net_pips']} пп, PF {d['profit_factor']}, "
                             f"{d['verdict']}" if "trades" in d else f"\n    {d['pair']}: {d['note']}")
                if res["status"] == "не прошло проверки":
                    line += " - " + "; ".join(res["attempts"][-1]["errors"])[:500]
            except Exception as e:  # сбой одной спеки не останавливает остальные
                bad += 1
                line = f"{name}: СБОЙ {e}"
        print(line, flush=True)
        summary.append(line)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(summary) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
