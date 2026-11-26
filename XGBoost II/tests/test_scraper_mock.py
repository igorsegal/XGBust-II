# Проверка сборщика без сети: подмена playwright. Сценарии: обычный сбор, 403, страница проверки на робота (200), 429 на списке,
# пауза 12 часов после блокировки, снятие паузы, большая статья с фразой-маркером внутри текста.
import sys, types, os, json, tempfile, time, importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(); os.environ["XGB_DATA"] = tmp; os.environ["XGB_BATCH"] = "3"
SCEN = {}; REQ = []; SLEEPS = []
def art_html(n, body_extra=""):
    text = ("Trading rule entry exit stop. " * 200) + body_extra
    return f'<html><head><meta property="og:title" content="Article {n}"><meta property="article:published_time" content="2024-05-01"></head><body><div class="article-body">{text}</div></body></html>'
LIST = '<html><body>' + ''.join(f'<a href="/en/articles/{1000+i}">a</a>' for i in range(8)) + '</body></html>'
class Resp:
    def __init__(s, st): s.status = st
class Page:
    def __init__(s): s.html = ""
    def goto(s, url, **k):
        REQ.append(url); st, html = SCEN(url); s.html = html; return Resp(st)
    def content(s): return s.html
    def wait_for_timeout(s, ms): pass
class Ctx:
    def add_init_script(s, x): pass
    def new_page(s): return Page()
class Br:
    def new_context(s, **k): return Ctx()
    def close(s): pass
class Chromium:
    def launch(s, **k): return Br()
class PW:
    chromium = Chromium()
    def __enter__(s): return s
    def __exit__(s, *a): return False
fake = types.ModuleType("playwright.sync_api"); fake.sync_playwright = lambda: PW()
sys.modules["playwright"] = types.ModuleType("playwright"); sys.modules["playwright.sync_api"] = fake
import src.scraper as sc
sc.time.sleep = lambda x: SLEEPS.append(x)
def run(scen, label):
    global SCEN; REQ.clear(); SLEEPS.clear(); SCEN = scen
    importlib.reload(sc); sc.time.sleep = lambda x: SLEEPS.append(x)
    got, cur = sc.collect_batch(); sc.save_cursor(cur)
    print(f"{label}: запросов {len(REQ)}, собрано {len(got)}, blocked_utc={'есть' if cur.get('blocked_utc') else 'нет'}, страница курсора {cur['backfill_page']}")
    return got, cur
ok = True
def check(c, m):
    global ok
    print(("  OK  " if c else "  ОШИБКА ") + m); ok = ok and c
# A обычный сбор
def A(url): return (200, LIST if "/articles/" not in url.replace("/en/articles/mt5","").split("articles")[-1][1:2] and url.rstrip("/").split("/")[-1] in ("machine_learning","page2") else art_html(url.split("/")[-1]))
def isl(url): return url.rstrip("/").split("/")[-1] in ("trading_systems", "machine_learning", "page2", "page3")
def A(url): return (200, LIST) if isl(url) else (200, art_html(url.split("/")[-1]))
g, c = run(A, "A обычный")
check(len(g) == 3, "собрано ровно 3 (по лимиту XGB_BATCH)"); check(all(5.0 <= x <= 15.0 for x in SLEEPS) and len(SLEEPS) == len(REQ) - 1, f"паузы между запросами {min(SLEEPS):.1f}..{max(SLEEPS):.1f} с, их {len(SLEEPS)}")
check("blocked_utc" not in c, "флага блокировки нет")
# B 403 на второй статье
os.remove(sc.CURSOR_PATH); open(sc.SEEN_URLS_PATH, "w").close()
n = {"k": 0}
def B(url):
    if isl(url): return (200, LIST)
    n["k"] += 1; return (403, "denied") if n["k"] == 2 else (200, art_html(url.split("/")[-1]))
g, c = run(B, "B 403 на второй статье")
check(len(g) == 1 and "blocked_utc" in c, "собрана 1 статья, флаг блокировки записан")
check(len(REQ) == 3, f"после блокировки запросов нет (всего {len(REQ)}: список + 2 статьи)")
# D повторный запуск сразу
g, c = run(A, "D повтор сразу после блокировки")
check(len(REQ) == 0 and len(g) == 0, "сайт не трогаем 12 часов")
# E через 13 часов
cur = json.load(open(sc.CURSOR_PATH)); cur["blocked_utc"] = int(time.time()) - 13 * 3600; json.dump(cur, open(sc.CURSOR_PATH, "w"))
g, c = run(A, "E через 13 часов")
check(len(g) == 3 and "blocked_utc" not in c, "сбор возобновился, флаг снят")
# C проверка на робота со статусом 200
os.remove(sc.CURSOR_PATH); open(sc.SEEN_URLS_PATH, "w").close()
def C(url): return (200, LIST) if isl(url) else (200, "<html><title>Just a moment...</title><body>Checking your browser</body></html>")
g, c = run(C, "C страница проверки (200)")
check(len(g) == 0 and "blocked_utc" in c and len(REQ) == 2, "остановка на первой же проверке")
# F 429 на списке
os.remove(sc.CURSOR_PATH)
def F(url): return (429, "slow down")
g, c = run(F, "F 429 на списке")
check(len(REQ) == 1 and "blocked_utc" in c, "один запрос и остановка")
# G длинная статья с маркером в тексте
os.remove(sc.CURSOR_PATH); open(sc.SEEN_URLS_PATH, "w").close()
def G(url): return (200, LIST) if isl(url) else (200, art_html(url.split("/")[-1], body_extra=(" Just a moment. Verify you are human. " + "x " * 40000)))
g, c = run(G, "G длинная статья с фразой-маркером")
check(len(g) == 3 and "blocked_utc" not in c, "обычная статья с такой фразой не считается блокировкой")
# H смена порядка разделов: старый курсор начинает с торговых систем, просмотренное не берётся повторно
json.dump({"section_idx": 0, "backfill_page": 5, "cutoff_year": 2018, "backfill_completed": False}, open(sc.CURSOR_PATH, "w"))
open(sc.SEEN_URLS_PATH, "w").write("https://www.mql5.com/en/articles/1000\n")
g, c = run(A, "H старый курсор")
check(REQ[0].endswith("/mt5/trading_systems"), "первый запрос - список торговых систем, страница 1")
check(c["order"] == sc.SECTIONS_ORDER and c["section_idx"] == 0 and c["cutoff_year"] == 2018, "курсор переведён на новый порядок")
check(all(not x["url"].endswith("/1000") for x in g) and len(g) == 3, "просмотренная статья не взята повторно")
# I новый курсор не сбрасывается
json.dump({"section_idx": 1, "backfill_page": 3, "cutoff_year": 2018, "backfill_completed": False, "order": sc.SECTIONS_ORDER}, open(sc.CURSOR_PATH, "w"))
g, c = run(A, "I новый курсор")
check(REQ[0].endswith("/mt5/machine_learning/page3"), "курсор нового порядка продолжается со своего места")
print("ИТОГ:", "ВСЕ ПРОВЕРКИ ПРОШЛИ" if ok else "ЕСТЬ ОШИБКИ")
