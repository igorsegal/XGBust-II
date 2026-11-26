"""Проверки spec_to_rule с подставной моделью и настоящим тестером на придуманных свечах.
    python tests/test_spec_to_rule.py путь\\к\\tester.exe"""
import calendar
import io
import json
import math
import os
import random
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "registry"))
os.environ.update(JURY_PAUSE="0", DASHSCOPE_API_KEY="SECRET-KEY-123", XGB_DATA=tempfile.mkdtemp())
import spec_to_rule as s2r  # noqa: E402
from src import jury  # noqa: E402

TESTER = os.path.abspath(sys.argv[1])
bad = 0


def check(name, got, want=True):
    global bad
    ok = got == want
    bad += 0 if ok else 1
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else f" got={got!r} want={want!r}"))


tmp = tempfile.mkdtemp()
bars, out, specs = (os.path.join(tmp, n) for n in ("bars", "out", "specs"))
os.makedirs(os.path.join(bars, "EURUSD"))
os.makedirs(specs)
random.seed(1)
recs, price, t = [], 1.10, calendar.timegm((2020, 1, 1, 0, 0, 0))
while t < calendar.timegm((2025, 3, 1, 0, 0, 0)):
    if (t // 86400 + 3) % 7 < 5:
        o = price
        price = max(0.5, price + random.gauss(0, 0.001) + 0.00003 * math.sin(t / 3e5))
        recs.append(struct.pack("<qddddqiq", t, o, max(o, price) + 0.0004, min(o, price) - 0.0004, price, 100, 10, 0))
    t += 3600
with open(os.path.join(bars, "EURUSD", "EURUSD_H1.bin"), "wb") as f:
    f.write(b"XFBAR001" + struct.pack("<iiiidqqqi", 1, 60, 3600, 5, 0.00001, len(recs), 0, 0, 6) + b"EURUSD")
    f.write(b"".join(recs))


def spec(num, **kw):
    d = {"url": f"https://www.mql5.com/en/articles/{num}", "title": f"Spec {num}", "published_year": 2026,
         "entry_long": "close выше SMA 20", "entry_short": "close ниже SMA 20", "formula_and_logic": "SMA 20", **kw}
    json.dump(d, open(os.path.join(specs, f"{num}.json"), "w", encoding="utf-8"), ensure_ascii=False)


good = {"expressible": True, "name": "SMA cross", "direction": "both", "timeframes": ["H1"], "pairs": ["EURUSD"],
        "params": {"n": {"type": "int", "default": 20, "min": 2, "max": 100}},
        "inputs": [{"name": "ma", "indicator": "SMA", "params": {"period": "$n"}}],
        "entry_long_expr": "crossup(close, ma)", "entry_short_expr": "crossdown(close, ma)",
        "implementation": {"kind": "cpp", "file": "evil.h"}, "status": "tested_pass"}
wrong = {**good, "entry_long_expr": "crossup(close, nothing)"}
queue = {"translator": [], "checker": []}
sent = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake(req, timeout=0):
    body = json.loads(req.data)
    system = body["messages"][0]["content"]
    role = next(r for r, p in jury.OTHER_ROLES.items() if system.startswith(p))
    sent.append((role, body["messages"][1]["content"]))
    q = queue[role]
    ans = q.pop(0) if len(q) > 1 else q[0]
    return Resp(json.dumps({"choices": [{"message": {"content": json.dumps(ans, ensure_ascii=False)}}]},
                           ensure_ascii=False).encode("utf-8"))


jury.urllib.request.urlopen = fake
commands = []
real_run = s2r.run_cmd
s2r.run_cmd = lambda cmd: (commands.append(cmd), real_run(cmd))[1]
reg_path = os.path.join(ROOT, "registry", "rules_registry.json")
before = open(reg_path, "rb").read()
argv = ["--specs", specs, "--out", out, "--bars", bars, "--tester", TESTER]


def run(num, translator, checker, **kw):
    for f in os.listdir(specs):
        os.remove(os.path.join(specs, f))
    spec(num, **kw)
    sent.clear()
    commands.clear()
    queue["translator"], queue["checker"] = list(translator), list(checker)
    code = s2r.main(argv)
    path = os.path.join(out, f"{num}.json")
    return code, json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


ok = {"matches": True, "differences": []}
code, r = run(90001, [wrong, good], [ok])
check("после ошибки реестра исправлено", (code, r["status"], len(r["attempts"])), (0, "проверено", 2))
check("ошибка вернулась модели", any(role == "translator" and "неизвестное имя в условии: nothing" in text for role, text in sent))
check("модель не может задать реализацию и статус", (r["rule"]["implementation"], r["rule"]["status"]),
      ({"kind": "expr"}, "implemented_untested"))
check("есть результат разработки по EURUSD", r["development"][0]["trades"] > 100)
check("для остальных пар названо отсутствие баров", r["development"][1]["note"], "нет файла баров")
check("экзамен не открывался", any("--exam" in c for c in commands), False)
check("самопроверка на будущее запускалась", any("--selftest" in c for c in commands))
res = json.load(open(os.path.join(out, "results", "ART_90001_01_EURUSD_H1.json"), encoding="utf-8"))
check("история обрезана до экзамена", res["history"].split(" .. ")[1] < "2025-01-01")
check("реестр не изменён", open(reg_path, "rb").read() == before)
check("временные файлы убраны", [f for f in os.listdir(os.path.join(ROOT, "registry")) if f.startswith("_draft")], [])

code, r = run(90002, [good], [{"matches": False, "differences": ["сдвиг бара другой"]}, ok])
check("расхождение со спекой вернулось и исправлено", (r["status"], r["attempts"][0]["errors"]),
      ("проверено", ["расхождение со SPEC: сдвиг бара другой"]))
check("торговые числа модели не показаны", any(w in text for _, text in sent for w in ("net_pips", "profit_factor", "нетто")), False)

code, r = run(90003, [good], [{"matches": False, "differences": ["не то"]}])
check("три неудачи: не прошло", (r["status"], len(r["attempts"]), sum(x[0] == "translator" for x in sent)),
      ("не прошло проверки", 3, 3))
check("и на истории не считалось", commands, [])

code, r = run(90004, [{"expressible": False, "reason": "нужна обучаемая модель"}], [ok])
check("невыразимое честно помечено", (r["status"], len(sent)), ("нужен код", 1))

code, r = run(90005, [good], [ok], edge_type="Feature_Or_Filter")
check("признак не переводится", (r, len(sent)), (None, 0))
code, r = run(25064, [good], [ok])
check("статья уже в реестре пропущена", (r, len(sent)), (None, 0))
code, r = run(90001, [good], [ok])
check("готовый черновик не переделывается", len(sent), 0)

bars_arg = argv[argv.index("--bars") + 1]
argv[argv.index("--bars") + 1] = os.path.join(tmp, "nowhere")
code, r = run(90006, [good], [ok])
check("нет баров: сбой окружения, модели не возвращается", (code, r, sum(x[0] == "translator" for x in sent)), (1, None, 1))
check("ключа в журналах нет", any("SECRET-KEY-123" in open(os.path.join(out, "raw", f), encoding="utf-8").read()
      for f in os.listdir(os.path.join(out, "raw"))), False)
print("ИТОГ:", "ВСЕ ПРОВЕРКИ ПРОШЛИ" if bad == 0 else f"ОШИБОК: {bad}")
sys.exit(1 if bad else 0)
