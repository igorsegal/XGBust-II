import sys, os, json, tempfile, importlib, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# playwright is not needed for these checks
pw = types.ModuleType("playwright"); sp = types.ModuleType("playwright.sync_api")
sp.sync_playwright = lambda: None; sp.TimeoutError = Exception
sys.modules.setdefault("playwright", pw); sys.modules.setdefault("playwright.sync_api", sp)
from bs4 import BeautifulSoup
import src.scraper as sc

bad = 0
def check(name, got, want):
    global bad
    ok = got == want
    bad += 0 if ok else 1
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else f" got={got!r} want={want!r}"))

def t(html): return sc._find_title(BeautifulSoup(html, "lxml"))
check("og:title", t('<meta property="og:title" content="A B C"><h1>x</h1>'), "A B C")
check("twitter:title", t('<meta name="twitter:title" content="Tw T">'), "Tw T")
check("json-ld", t('<script type="application/ld+json">{"headline": "LD Head \\"q\\" x"}</script>'), 'LD Head "q" x')
check("h1", t("<h1> H  One </h1>"), "H One")
check("title tag without site suffix", t("<title>Some Name - MQL5 Articles</title>"), "Some Name")
check("title keeps inner dash", t("<title>Part 2 - Risk - Sizing - MQL5 Articles</title>"), "Part 2 - Risk - Sizing")
check("h2 fallback", t("<h2>Only H2</h2>"), "Only H2")
check("nothing -> Untitled", t("<p>no head</p>"), "Untitled")
d = "/mnt/user-data/uploads/XGBoost-edge-git/data/debug"
if os.path.isdir(d):
    for f, want in (("sample0_22887.html", "Corona Virus Optimization (CVO) Algorithm"),
                    ("sample1_22674.html", "How to Build a 29-Pair Portfolio with an L1 Filter and VaR-based Allocation of Lots")):
        p = os.path.join(d, f)
        if os.path.exists(p):
            check("real page " + f, t(open(p, encoding="utf-8").read()), want)

tmp = tempfile.mkdtemp(); os.environ["XGB_DATA"] = tmp
import src.jury as jr
importlib.reload(jr)
line = lambda u: json.dumps({"url": u, "title": "T"}, ensure_ascii=False)
open(jr.PASSED_PATH, "w", encoding="utf-8").write("\n".join([line("u1"), line("u1"), line("u2"), ""]))
check("dedupe removes 1", jr.dedupe_passed(), 1)
check("file has 2 lines", len([x for x in open(jr.PASSED_PATH, encoding="utf-8").read().splitlines() if x]), 2)
check("dedupe idempotent", jr.dedupe_passed(), 0)
check("already_passed true", jr._already_passed("u2"), True)
check("already_passed false", jr._already_passed("u9"), False)
print("ИТОГ:", "ВСЕ ПРОВЕРКИ ПРОШЛИ" if bad == 0 else f"ОШИБОК: {bad}")
sys.exit(1 if bad else 0)
