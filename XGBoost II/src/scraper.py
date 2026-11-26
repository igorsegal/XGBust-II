import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
BASE_URL = "https://www.mql5.com"
TARGET_SECTIONS = [
    "https://www.mql5.com/en/articles/mt5/trading_systems",
    "https://www.mql5.com/en/articles/mt5/machine_learning",
    "https://www.mql5.com/en/articles",
]
DATA_DIR = os.getenv("XGB_DATA", "data")  # тестовый режим: XGB_DATA=data_test
SEEN_URLS_PATH = os.path.join(DATA_DIR, "seen_urls.txt")
CURSOR_PATH = os.path.join(DATA_DIR, "cursor.json")
BATCH_LIMIT = int(os.getenv("XGB_BATCH", "15"))  # тест: XGB_BATCH=5
CUTOFF_YEAR = 2018
SECTIONS_ORDER = 2  # номер порядка разделов; при смене порядка курсор начинает с первого раздела (2: сначала торговые системы)
def load_seen_urls() -> Set[str]:
    if not os.path.exists(SEEN_URLS_PATH):
        return set()
    with open(SEEN_URLS_PATH, "r", encoding="utf-8-sig") as f:
        return {line.strip() for line in f if line.strip()}
def append_seen_url(url: str) -> None:
    os.makedirs(os.path.dirname(SEEN_URLS_PATH), exist_ok=True)
    with open(SEEN_URLS_PATH, "a", encoding="utf-8") as f:
        f.write(url + "\n")
def load_cursor() -> Dict:
    if not os.path.exists(CURSOR_PATH):
        return {"section_idx": 0, "backfill_page": 1, "cutoff_year": CUTOFF_YEAR, "backfill_completed": False,
                "order": SECTIONS_ORDER}
    with open(CURSOR_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    data.setdefault("section_idx", 0)
    data.setdefault("backfill_page", 1)
    data.setdefault("cutoff_year", CUTOFF_YEAR)
    data.setdefault("backfill_completed", False)
    if data.get("order") != SECTIONS_ORDER:
        # курсор записан для другого порядка разделов; просмотренные статьи помнит seen_urls.txt, повторно они не берутся
        data.update(section_idx=0, backfill_page=1, backfill_completed=False, order=SECTIONS_ORDER)
    return data
def save_cursor(cursor: Dict) -> None:
    os.makedirs(os.path.dirname(CURSOR_PATH), exist_ok=True)
    with open(CURSOR_PATH, "w", encoding="utf-8") as f:
        json.dump(cursor, f, indent=2)
def polite_sleep(step_count: int) -> None:
    time.sleep(random.uniform(5.0, 15.0))  # случайная пауза 5-15 с между любыми двумя запросами


BLOCK_PAUSE_SEC = 12 * 3600  # после блокировки сайта следующий запуск не обращается к сайту 12 часов
ROBOT_MARKERS = ("Just a moment", "cf-browser-verification", "/cdn-cgi/challenge", "challenge-platform",
                 "Attention Required! | Cloudflare", "Checking your browser", "Verify you are human")


def is_robot_page(html: str) -> bool:
    """Страница проверки на робота (Cloudflare и подобные): короткая страница с характерными признаками."""
    return len(html) < 60000 and any(m in html for m in ROBOT_MARKERS)


def fetch_html_browser(page, url: str) -> Optional[str]:
    """Текст страницы; "BLOCKED" при ответе 403/429/503 или странице проверки на робота."""
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=35000)
        if not resp:
            return None
        if resp.status in (403, 429, 503):
            return "BLOCKED"
        page.wait_for_timeout(1500)
        html = page.content()
        if is_robot_page(html):
            return "BLOCKED"
        return html
    except Exception:
        return None


def extract_article_links(list_html: str) -> List[str]:
    soup = BeautifulSoup(list_html, "lxml")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        if re.match(r"^/en/articles/\d+$", href):
            full_url = urljoin(BASE_URL, href)
            if full_url not in links:
                links.append(full_url)
    return links
def _find_year(html: str, soup) -> Optional[int]:
    """Год публикации. Надёжные источники первыми; если нет - None."""
    for pat in (
        r'article:published_time"\s+content="(20\d{2})',
        r'"datePublished"\s*:\s*"(20\d{2})',
        r'itemprop="datePublished"[^>]*content="(20\d{2})',
    ):
        m = re.search(pat, html)
        if m:
            return int(m.group(1))
    time_tag = soup.find("time")
    if time_tag:
        m = re.search(r"(20\d{2})", time_tag.get("datetime") or time_tag.get_text(strip=True))
        if m:
            return int(m.group(1))
    return None


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    for suffix in (" - MQL5 Articles", " - MQL5", " | MQL5 Articles"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return t


def _find_title(soup) -> str:
    """Заголовок: несколько запасных способов, 'Untitled' только если нет ни одного."""
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}, {"name": "title"}):
        m = soup.find("meta", attrs=attrs)
        if m and _clean_title(m.get("content")):
            return _clean_title(m.get("content"))
    for sc in soup.find_all("script", type="application/ld+json"):
        mm = re.search(r'"headline"\s*:\s*"((?:[^"\\]|\\.)+)"', sc.string or sc.get_text() or "")
        if mm and _clean_title(mm.group(1)):
            return _clean_title(mm.group(1).replace('\\"', '"'))
    for tag in ("h1",):
        h = soup.find(tag)
        if h and _clean_title(h.get_text(" ", strip=True)):
            return _clean_title(h.get_text(" ", strip=True))
    if soup.title and _clean_title(soup.title.get_text()):
        return _clean_title(soup.title.get_text())
    h2 = soup.find("h2")
    if h2 and _clean_title(h2.get_text(" ", strip=True)):
        return _clean_title(h2.get_text(" ", strip=True))
    return "Untitled"


def _find_body(soup) -> str:
    """Самый вложенный блок с большим текстом (без боковых меню и шапки)."""
    best = None
    for div in soup.find_all("div", class_=re.compile(r"(article|content|text)", re.I)):
        t = div.get_text("\n", strip=True)
        if len(t) >= 3000 and (best is None or len(t) < len(best)):
            best = t
    return best if best else soup.get_text("\n", strip=True)


def parse_article_page(html: str, url: str) -> Optional[Dict]:
    soup = BeautifulSoup(html, "lxml")
    pub_year = _find_year(html, soup)
    title = _find_title(soup)
    if title == "Untitled":
        print(f"  [ВНИМАНИЕ] нет заголовка у {url}")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    raw_text = _find_body(soup)
    if len(raw_text) < 500:
        return None
    return {
        "url": url,
        "title": title,
        "published_year": pub_year,
        "text": raw_text[:45000],
    }


DEBUG_DIR = os.path.join(DATA_DIR, "debug")


def _debug_dump(link: str, html: str, n: int) -> None:
    """Сырой HTML первых двух статей запуска: чтобы видеть реальную вёрстку MQL5."""
    if n >= 2:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    m = re.search(r"/articles/(\d+)", link)
    with open(os.path.join(DEBUG_DIR, f"sample{n}_{m.group(1) if m else n}.html"), "w", encoding="utf-8") as f:
        f.write(html)


def collect_batch() -> Tuple[List[Dict], Dict]:
    from playwright.sync_api import sync_playwright
    seen_urls = load_seen_urls()
    cursor = load_cursor()
    next_cursor = dict(cursor)
    blocked_at = int(cursor.get("blocked_utc") or 0)
    if blocked_at and time.time() - blocked_at < BLOCK_PAUSE_SEC:
        print(f"[BLOCKED] сайт блокировал прошлый запуск ({time.strftime('%Y-%m-%d %H:%M', time.gmtime(blocked_at))} UTC): "
              "сбор пропущен, суд работает по очереди")
        return [], next_cursor
    next_cursor.pop("blocked_utc", None)
    collected: List[Dict] = []
    request_counter = 0
    blocked = False
    dumped = 0
    with sync_playwright() as p:
        executable = "/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None
        browser = p.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        try:
            while (
                len(collected) < BATCH_LIMIT
                and not next_cursor.get("backfill_completed", False)
                and not blocked
            ):
                sec_idx = next_cursor["section_idx"]
                if sec_idx >= len(TARGET_SECTIONS):
                    next_cursor["backfill_completed"] = True
                    break
                base_sec_url = TARGET_SECTIONS[sec_idx]
                page_num = next_cursor["backfill_page"]
                page_url = f"{base_sec_url}/page{page_num}" if page_num > 1 else base_sec_url
                if request_counter > 0:
                    polite_sleep(request_counter)
                page_html = fetch_html_browser(page, page_url)
                request_counter += 1
                if page_html == "BLOCKED":
                    blocked = True
                    print(f"[BLOCKED] {page_url}: остановка сбора")
                    break
                if not page_html:
                    next_cursor["section_idx"] = sec_idx + 1
                    next_cursor["backfill_page"] = 1
                    continue
                links = extract_article_links(page_html)
                if not links:
                    next_cursor["section_idx"] = sec_idx + 1
                    next_cursor["backfill_page"] = 1
                    continue
                reached_cutoff = False
                for link in links:
                    if len(collected) >= BATCH_LIMIT or blocked:
                        break
                    if link in seen_urls:
                        continue
                    polite_sleep(request_counter)
                    article_html = fetch_html_browser(page, link)
                    request_counter += 1
                    if article_html == "BLOCKED":
                        blocked = True
                        print(f"[BLOCKED] {link}: остановка сбора")
                        break
                    if not article_html:
                        continue
                    _debug_dump(link, article_html, dumped)
                    dumped += 1
                    parsed = parse_article_page(article_html, link)
                    if not parsed:
                        append_seen_url(link)
                        seen_urls.add(link)
                        continue
                    if parsed["published_year"] is not None and parsed["published_year"] < next_cursor.get("cutoff_year", CUTOFF_YEAR):
                        reached_cutoff = True
                        break
                    collected.append(parsed)
                    seen_urls.add(link)
                if reached_cutoff:
                    next_cursor["section_idx"] = sec_idx + 1
                    next_cursor["backfill_page"] = 1
                elif len(collected) < BATCH_LIMIT and not blocked:
                    next_cursor["backfill_page"] = page_num + 1
        finally:
            browser.close()
    if blocked:
        next_cursor["blocked_utc"] = int(time.time())
    return collected, next_cursor