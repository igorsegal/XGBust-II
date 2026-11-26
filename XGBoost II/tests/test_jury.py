"""Проверки жюри с подставной моделью: сеть и ключ не нужны.  python tests/test_jury.py"""
import importlib
import io
import json
import os
import sys
import tempfile
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ.update(XGB_DATA=tmp, JURY_PAUSE="0", DASHSCOPE_API_KEY="SECRET-KEY-123")
os.environ.pop("XGB_REJUDGE", None)
os.environ.pop("JURY_LIMIT", None)
for name in ("OPENROUTER_API_KEY", "JURY_PROVIDER", "JURY_JUDGE_MODEL", "JURY_WORKER_MODEL", "XGB_GOLDEN"):
    os.environ.pop(name, None)
import src.jury as jr
jr._read_key_file = lambda name: ""  # настоящие файлы с ключами проверкам не нужны
import src.golden as gd

bad = 0


def check(name, got, want=True):
    global bad
    ok = got == want
    bad += 0 if ok else 1
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else f" got={got!r} want={want!r}"))


TEXT = ("Introduction. The indicator is computed on every closed bar only.\n"
        "We buy when velocity is above zero and acceleration turns positive.\n"
        "The window length is InpWindow = 21 bars, the order is 3. " * 3)
Q1 = {"about": "bar", "quote": "The indicator is computed on every closed bar only."}
Q2 = {"about": "entry", "quote": "We buy when velocity is above zero and acceleration turns positive."}
FAKE = {"about": "x", "quote": "The author proves a profit factor of nine."}
CHECKS = {"repaint": {"status": "нет"}, "higher_tf": {"status": "нет"}, "tick_volume": {"status": "не нужен"}}


def passing(**kw):
    v = {"verdict": "PASS", "edge_type": "Strategy", "formula_and_logic": "Скорость и ускорение полинома по 21 бару",
         "entry_long": "скорость > 0 и ускорение стало > 0", "entry_short": "", "checks": CHECKS,
         "source_quotes": [Q1, Q2]}
    v.update(kw)
    return v


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


calls, judge_answers = [], []


def fake_urlopen(req, timeout=0):
    body = json.loads(req.data)
    system = body["messages"][0]["content"]
    role = next(r for r in jr.ROLES if system.startswith(jr.ROLES[r]))
    calls.append((role, body))
    if role == "judge":
        ans = judge_answers.pop(0) if len(judge_answers) > 1 else judge_answers[0]
        if isinstance(ans, Exception):
            raise ans
    elif role == "advocate":
        ans = {"for": ["a"], "strength": 5}
    else:
        ans = {"against": [], "fatal": False, "non_fatal": []}
    return Resp(json.dumps({"choices": [{"message": {"content": json.dumps(ans, ensure_ascii=False)}}]},
                           ensure_ascii=False).encode("utf-8"))


jr.urllib.request.urlopen = fake_urlopen


def article(n, status="pending", **kw):
    os.makedirs(jr.CAND_DIR, exist_ok=True)
    d = {"url": f"https://x/{n}", "title": f"Art {n}", "published_year": 2026, "text": TEXT, "status": status, **kw}
    json.dump(d, open(os.path.join(jr.CAND_DIR, f"{n}.json"), "w", encoding="utf-8"), ensure_ascii=False)


def load(n):
    return json.load(open(os.path.join(jr.CAND_DIR, f"{n}.json"), encoding="utf-8"))


def run(n, *answers, status="pending", **kw):
    calls.clear()
    judge_answers[:] = list(answers)
    for f in os.listdir(jr.CAND_DIR) if os.path.isdir(jr.CAND_DIR) else []:
        os.remove(os.path.join(jr.CAND_DIR, f))
    article(n, status, **kw)
    jr.run_pending()
    return load(n), [c[0] for c in calls]


def passed_lines():
    if not os.path.exists(jr.PASSED_PATH):
        return []
    return [json.loads(x) for x in open(jr.PASSED_PATH, encoding="utf-8") if x.strip()]


# --- цитаты
q = jr.check_quotes([Q1, Q2, FAKE, {"quote": "closed bar"}, Q1], TEXT)
check("две настоящие цитаты найдены, повтор не считается", len(q["found"]), 2)
check("выдуманная и слишком короткая не найдены", len(q["missing"]), 2)
check("перенос строки и знаки не мешают", len(jr.check_quotes(
    ["every closed bar only — We buy when velocity"], TEXT)["found"]), 1)
check("перевод не засчитывается", len(jr.check_quotes(["Мы покупаем когда скорость выше нуля"], TEXT)["found"]), 0)
check("мусор вместо списка", jr.check_quotes("строка", TEXT)["found"], [])

# --- стратегия
d, roles = run(1, passing())
check("Strategy принята с первого раза", (d["status"], len(roles)), ("passed", 3))
check("число подтверждённых цитат записано", d["jury"]["program_check"]["confirmed"], 2)
check("строка в passed_edges с видом", passed_lines()[-1]["edge_type"], "Strategy")
check("spec создан", os.path.exists(os.path.join(jr.SPEC_DIR, "1.json")))

# --- признак без входа
feat = passing(edge_type="Feature_Or_Filter", entry_long="", feature_output="ускорение, число, вход модели")
d, roles = run(2, feat)
check("признак без условия входа принят", (d["status"], len(roles)), ("passed", 3))

# --- выдуманные цитаты: переспрос и отказ
d, roles = run(3, passing(source_quotes=[FAKE]))
check("выдуманные цитаты: судья переспрошен один раз", roles.count("judge"), 2)
check("и статья отклонена", d["status"], "rejected")
check("причина названа", "подтверждено цитат: 0" in d["jury"]["judge"]["reject_reason"])
check("отклонённой нет в passed_edges", any(x["url"] == "https://x/3" for x in passed_lines()), False)
check("переспрос содержит замечание", "ПРОГРАММА ПРОВЕРИЛА" in calls[-1][1]["messages"][1]["content"])

# --- исправился после переспроса
d, roles = run(4, passing(source_quotes=[Q1, FAKE]), passing(source_quotes=[Q1, Q2, FAKE]))
check("после переспроса принята", d["status"], "passed")
check("неподтверждённая цитата убрана из правила", len(d["jury"]["judge"]["source_quotes"]), 2)
check("но записана в проверке", len(d["jury"]["program_check"]["unconfirmed"]), 1)

d, roles = run(5, passing(source_quotes=[]), {"verdict": "REJECT", "reject_reason": "нечем подтвердить"})
check("после переспроса судья сам отклонил", (d["status"], d["jury"]["judge"]["reject_reason"]),
      ("rejected", "нечем подтвердить"))
check("замечания первого раза сохранены", bool(d["jury"]["program_check"]["first_remarks"]))

# --- прочие проверки
d, roles = run(6, passing(entry_long=""))
check("Strategy без входа отклонена", d["status"], "rejected")
d, roles = run(7, passing(edge_type="Feature_Or_Filter", entry_long=""))
check("признак без feature_output отклонён", d["status"], "rejected")
d, roles = run(8, passing(checks={**CHECKS, "repaint": {"status": "неустранимо"}}))
check("неустранимая перерисовка: отказ без переспроса", (d["status"], roles.count("judge")), ("rejected", 1))
d, roles = run(9, passing(checks={**CHECKS, "higher_tf": {"status": "Неустранимо"}}))
check("незакрытый старший таймфрейм: отказ", d["status"], "rejected")
d, roles = run(10, passing(checks={**CHECKS, "repaint": {"status": "исправимо"}}))
check("исправимая проблема не мешает", d["status"], "passed")
d, roles = run(11, passing(checks={}))
check("без checks не принимается", d["status"], "rejected")
d, roles = run(12, {"verdict": "REJECT", "reject_reason": "инфраструктура"})
check("обычный отказ: три обращения", (d["status"], len(roles)), ("rejected", 3))

# --- журнал запрос-ответ
raw_path = os.path.join(jr.RAW_DIR, "1.jsonl")
rows = [json.loads(x) for x in open(raw_path, encoding="utf-8")]
check("три строки с тегами шагов", [r["step"] for r in rows], ["advocate", "prosecutor", "judge"])
blob = open(raw_path, encoding="utf-8").read()
check("ключа в журнале нет", "SECRET-KEY-123" in blob, False)
check("текст статьи заменён меткой", ("ТЕКСТ СТАТЬИ candidates/1.json sha256=" in blob, "InpWindow = 21 bars" in
      rows[0]["request"]["messages"][1]["content"]), (True, False))
check("полное задание роли сохранено", rows[1]["request"]["messages"][0]["content"].startswith(jr.ROLES["prosecutor"]))
mark_back = rows[0]["request"]["messages"][1]["content"]
check("запрос восстанавливается точно", mark_back.replace(
    f"<<ТЕКСТ СТАТЬИ candidates/1.json sha256={jr._sha(TEXT)}>>", TEXT).endswith(TEXT))
check("сырой ответ сохранён", "choices" in rows[2]["response"])

# --- повторный суд: смена вердикта видна
os.environ["XGB_REJUDGE"] = "1"
old = {"judge": {}, "prompt_sha": "0000", "model": "m-old"}
d, roles = run(13, passing(), status="rejected", jury=old)
log = open(jr.LOG_PATH, encoding="utf-8").read()
check("смена вердикта в журнале", "вердикт изменился: rejected -> passed (задания изменились" in log)
check("прежний вердикт сохранён", d["jury"]["previous"]["status"], "rejected")
d, roles = run(14, passing(), status="rejected", jury={**old, "prompt_sha": jr.prompt_sha()})
check("при тех же заданиях так и написано",
      "(задания те же" in open(jr.LOG_PATH, encoding="utf-8").read())
os.environ.pop("XGB_REJUDGE")

# --- сбой сети: статья остаётся в очереди, обращение в журнале
d, roles = run(15, urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"rate limit")))
check("при 429 статья в очереди", d["status"], "pending")
check("ошибка 429 в сыром журнале", "HTTP 429" in open(os.path.join(jr.RAW_DIR, "15.jsonl"), encoding="utf-8").read())

# --- эталонный набор
os.makedirs(gd.GOLDEN_DIR, exist_ok=True)
for name, exp in (("a", {"verdict": "PASS", "edge_type": "Strategy"}), ("b", {"verdict": "REJECT"})):
    json.dump({"url": name, "title": name, "text": TEXT, "expected": exp},
              open(os.path.join(gd.GOLDEN_DIR, name + ".json"), "w", encoding="utf-8"))
before = (len(passed_lines()), len(os.listdir(jr.CAND_DIR)))
judge_answers[:] = [passing(), {"verdict": "REJECT", "reject_reason": "r"}]
check("всё совпало: код 0", gd.run(), 0)
judge_answers[:] = [passing()]
check("расхождение: код 1", gd.run(), 1)
res = open(os.path.join(gd.OUT_DIR, "last_result.txt"), encoding="utf-8").read()
check("в итоге названа ошибка", "ОШИБКА b" in res and "ИТОГ: верно 1 из 2" in res)
check("эталон не трогает кандидатов и passed", (len(passed_lines()), len(os.listdir(jr.CAND_DIR))), before)

# --- замок: новая версия заданий принимается только после полного успеха
check("после расхождения версия не принята", gd.check_accepted(), 1)
gd.record(jr.prompt_sha(), "qwen-plus", jr.prompt_sha() + " qwen-plus run")
check("отпечаток совпал: принята", gd.check_accepted(), 0)
saved = jr.ROLES["judge"]
jr.ROLES["judge"] = saved + " правка"
check("после правки задания снова не принята", gd.check_accepted(), 1)
jr.ROLES["judge"] = saved

# --- OpenRouter: сам включается только после эталонной проверки
os.environ["OPENROUTER_API_KEY"] = "OR-SECRET-456"
check("ключ есть, проверки не было: работает прежняя модель", jr._client()[1], "qwen-plus")
os.environ["JURY_PROVIDER"] = "openrouter"
cfg, model, _ = jr._client()
check("принудительно для проверки", (model, jr.model_id(cfg, model)), ("z-ai/glm-5.3-flash", "openrouter:z-ai/glm-5.3-flash"))
bodies = []


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def capture(req, timeout=0):
    bodies.append((req.full_url, json.loads(req.data)))
    return Answer(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8"))


real_urlopen = jr.urllib.request.urlopen
jr.urllib.request.urlopen = capture
jr._ask(cfg, model, "advocate", "x")
url, body = bodies[-1]
check("адрес, лёгкое размышление и запас на ответ", (url, body["reasoning"], body["max_tokens"]),
      ("https://openrouter.ai/api/v1/chat/completions", {"effort": "low"}, 7500))
check("закреплён один поставщик", body["provider"], {"only": ["z-ai"], "allow_fallbacks": False})
os.environ["JURY_JUDGE_MODEL"] = "google/gemini-3.5-flash-lite"
cfg, model, _ = jr._client()
jr._ask(cfg, model, "judge", "x")
check("судья на другой модели, без чужого поставщика", (bodies[-1][1]["model"], "provider" in bodies[-1][1]),
      ("google/gemini-3.5-flash-lite", False))
check("связка названа целиком", jr.model_id(cfg, model), "openrouter:z-ai/glm-5.3-flash+google/gemini-3.5-flash-lite")
jr._ask(cfg, model, "prosecutor", "x")
check("прокурор остаётся на рабочей", bodies[-1][1]["model"], "z-ai/glm-5.3-flash")
os.environ.pop("JURY_JUDGE_MODEL")
os.environ.pop("JURY_PROVIDER")
gd.record(jr.prompt_sha(), "openrouter:z-ai/glm-5.3-flash", jr.prompt_sha() + " openrouter:z-ai/glm-5.3-flash run")
check("после проверки включается сам", jr._client()[0].get("provider"), "openrouter")
check("прежнее принятие сохранено", gd.check_accepted(), 0)
os.environ["JURY_JUDGE_MODEL"] = "other/model"
check("другой судья не проверен: прежняя модель", jr._client()[1], "qwen-plus")
os.environ.pop("JURY_JUDGE_MODEL")
jr.ROLES["judge"] = saved + " правка"
check("новые задания новой моделью не проверены: прежняя", jr._client()[1], "qwen-plus")
jr.ROLES["judge"] = saved
gd.record(jr.prompt_sha(), "openrouter:z-ai/glm-5.3-flash", "")
check("отзыв принятия возвращает прежнюю", (jr._client()[1], gd.check_accepted()), ("qwen-plus", 0))
os.environ.pop("OPENROUTER_API_KEY")
os.environ["JURY_PROVIDER"] = "openrouter"
check("принудительно без ключа: суда нет, подмены нет", jr._client(), None)
os.environ.pop("JURY_PROVIDER")
jr.urllib.request.urlopen = real_urlopen

# --- настоящий набор в репозитории
real = os.path.join(ROOT, "data", "golden")
items = [json.load(open(os.path.join(real, f), encoding="utf-8")) for f in sorted(os.listdir(real)) if f.endswith(".json")]
check("в наборе 10 статей: 5 проходных и 5 мусорных",
      (len(items), sum(i["expected"]["verdict"] == "PASS" for i in items)), (10, 5))
check("у каждой есть текст", all(len(i["text"]) > 800 for i in items))

print("ИТОГ:", "ВСЕ ПРОВЕРКИ ПРОШЛИ" if bad == 0 else f"ОШИБОК: {bad}")
sys.exit(1 if bad else 0)
