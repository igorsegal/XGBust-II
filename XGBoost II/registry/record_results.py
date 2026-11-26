#!/usr/bin/env python3
"""record_results.py - переносит результаты тестов (results\\*.json) в реестр.
Статус правила считается по основным тестам (role=primary) новой схемы (скользящие окна):
  tested_fail - хоть один не прошёл разработку или экзамен; правило выключается по умолчанию;
  dev_pass    - все прошли разработку, но экзамен сдан не по всем;
  tested_pass - все прошли и разработку, и экзамен.
Файлы старой схемы (без поля mode) пропускаются.
Использование: python record_results.py [rules_registry.json] [results_dir]"""
import json, sys, os, glob, datetime
here = os.path.dirname(os.path.abspath(__file__))
reg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "rules_registry.json")
res_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "results")
reg = json.load(open(reg_path, encoding="utf-8-sig"))
byid = {r["id"]: r for r in reg["rules"]}
today = datetime.date.today().isoformat()
touched = set()
for f in sorted(glob.glob(os.path.join(res_dir, "*.json"))):
    d = json.load(open(f, encoding="utf-8-sig"))
    mode = d.get("mode")
    if mode not in ("dev", "exam"): continue
    for rr in d.get("rules", []):
        r = byid.get(rr["id"])
        if not r or r.get("status") == "example": continue   # учебные примеры в реестр результатов не заносятся
        old = next((x for x in r["results"] if x.get("test") == d["test_name"] and x.get("mode") == mode), None)
        rec = {"date": today, "test": d["test_name"], "mode": mode, "role": d.get("role", "primary"), "pair": d["pair"], "timeframe": d["timeframe"],
               "scheme": d["scheme"], "overrides": rr.get("overrides", "").strip(), mode: rr["segments"][0], "verdict": rr["verdict"], "tester": d.get("tester")}
        if old and {k: v for k, v in old.items() if k != "date"} == {k: v for k, v in rec.items() if k != "date"}: rec["date"] = old["date"]
        r["results"] = [x for x in r["results"] if not (x.get("test") == rec["test"] and x.get("mode") == mode)] + [rec]
        touched.add(rr["id"])
for rid in sorted(touched):
    r = byid[rid]
    prim = [x for x in r["results"] if x.get("mode") and x["role"] == "primary"]
    if not prim: continue
    dev = {x["test"] for x in prim if x["mode"] == "dev"}
    passed = {x["test"] for x in prim if x["mode"] == "exam" and x["verdict"] == "PASS"}
    if any(x["verdict"] != "PASS" for x in prim):
        r["status"] = "tested_fail"; r["enabled_by_default"] = False
    else:
        r["status"] = "tested_pass" if dev <= passed else "dev_pass"
    print(rid, r["status"], [(x["test"], x["mode"], x["verdict"]) for x in prim])
json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
