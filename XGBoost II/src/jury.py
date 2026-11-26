"""Фильтр 2: суд из трёх ролей. Необязателен: без ключа или при сбое
кандидаты просто остаются в очереди. Сканер от него не зависит."""
import glob
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.getenv("XGB_DATA", "data")
CAND_DIR = os.path.join(DATA_DIR, "candidates")
PASSED_PATH = os.path.join(DATA_DIR, "passed_edges.jsonl")
SPEC_DIR = os.path.join(DATA_DIR, "specs")
JURY_LIMIT = int(os.getenv("JURY_LIMIT", "0"))  # 0 = по умолчанию для провайдера
PAUSE_SEC = float(os.getenv("JURY_PAUSE", "6"))
LOG_PATH = os.path.join(DATA_DIR, "jury_log.txt")
RAW_DIR = os.path.join(DATA_DIR, "jury_raw")  # журнал «запрос - ответ» по статьям
ACCEPTED_PATH = os.path.join(os.getenv("XGB_GOLDEN") or os.path.join(DATA_DIR, "golden"), "accepted.txt")
MIN_QUOTES = 2
EDGE_TYPES = ("Strategy", "Feature_Or_Filter")
CHECK_NAMES = ("repaint", "higher_tf", "tick_volume")


def _log(msg: str) -> None:
    """Печать + файл в репозитории: итог каждого запуска виден без захода в журнал GitHub."""
    print(msg)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")

# Общие для прокурора и судьи: на этих случаях модель ошибочно ставила фатальный порок (прогон 2026-11-26)
NOT_FAULTS = (
    " НЕ являются пороками и не дают оснований для отказа: а) будущие цены в метке (целевой переменной) при "
    "обучении модели, если признаки и сигнал в момент решения считаются только по прошлым барам - это обычное "
    "обучение; б) расчёт по текущему незакрытому бару, который исправляется сдвигом на последний закрытый бар "
    "(это всегда 'исправимо'); в) скользящее окно из прошлых баров; г) сложность расчёта: регрессия, решение "
    "системы уравнений, итерации считаются точной формулой, если по тем же барам всегда дают то же число; "
    "д) обученная модель после признаков: если расчёт самих признаков описан точно, они годятся как "
    "Feature_Or_Filter, даже когда модель неинтерпретируема. "
)

ROLES = {
    "advocate": (
        "Ты адвокат идеи из статьи про торговлю на спот-форексе. Твоя задача: найти в тексте статьи конкретные "
        "основания считать, что описанное правило, признак или фильтр может давать торговое преимущество и что его "
        "можно проверить на исторических данных. Опирайся только на то, что реально написано в статье, и называй "
        "конкретные элементы (формулу, условие входа, фильтр, параметр, результат автора). Не повторяй общие слова. "
        "Если оснований нет, так и скажи. Ответ только JSON с ключами: for (список конкретных доводов из текста, "
        "по одной фразе) и strength (целое число от 0 до 10)."
    ),
    "prosecutor": (
        "Ты прокурор. Найди в статье конкретные пороки идеи, опираясь только на текст статьи. Нам годятся две вещи: "
        "торговое правило с условием входа ИЛИ рыночный признак либо фильтр, то есть величина, которая по точной "
        "формуле вычисляется из цен, спреда, тикового объёма или времени по закрытым барам и может быть входом "
        "модели XGBoost или разрешать и запрещать сделки. Отсутствие условия входа само по себе НЕ фатально, если "
        "есть такой признак или фильтр. Фатальными считай только такие пороки: (1) в сигнале или признаке "
        "используются данные будущих баров, в том числе перерисовывающийся расчёт, без которого идея теряет смысл "
        "(последнее колено ZigZag, центрированные фильтры, сглаживание или разложение по всему ряду, SSA, фильтр "
        "Ходрика-Прескотта, неподтверждённые фракталы); (2) нельзя записать точной формулой ни правило входа, ни "
        "признак или фильтр, потому что статья даёт лишь общее описание или архитектуру модели; (3) нужны данные, "
        "которых нет у спот-форекса (биржевой стакан, реальные объёмы, акции, криптовалюта); (4) в основе "
        "мартингейл, сетка или усреднение убытков; (5) статья не даёт ни торгового правила, ни рыночного признака "
        "или фильтра: инфраструктура, графика, оптимизатор, учебный пример, расчёт объёма позиции, разбор уже "
        "совершённых сделок. Проверь отдельно: перерисовку; берётся ли значение старшего таймфрейма только по "
        "последнему ЗАКРЫТОМУ бару; зависит ли идея от тикового объёма конкретного брокера. Если незакрытый бар или "
        "перерисовку можно заменить значением последнего закрытого бара без потери смысла, это не фатально."
        + NOT_FAULTS +
        "Отсутствие у автора теста вне выборки, спреда или комиссий фатальным НЕ считай: мы проверим идею сами. "
        "Такие недостатки назови отдельно. Ответ только JSON с ключами: against (список конкретных пороков с "
        "указанием, где в статье это видно), fatal (true или false), non_fatal (список недостатков, которые мы "
        "исправим при собственной проверке)."
    ),
    "judge": (
        "Ты судья. Даны текст статьи и доводы адвоката и прокурора. Вынеси вердикт PASS или REJECT. PASS бывает "
        "двух видов, укажи его в edge_type. Strategy: из статьи можно составить детерминированное правило для "
        "проверки на закрытых барах спот-форекса с условием входа (направление и условия), параметрами и значениями. "
        "Feature_Or_Filter: полного правила входа нет, но есть точная формула рыночного признака или фильтра, который "
        "вычисляется из цен, спреда, тикового объёма или времени по закрытым барам и может быть входом модели XGBoost "
        "или разрешать и запрещать сделки; тогда entry_long и entry_short оставь пустыми, а в feature_output напиши, "
        "какая величина получается, в каких пределах и как её применять. Если выход или стоп не описаны, это НЕ "
        "причина отказа: напиши в exit_rule или stop_rule 'не указан в статье'. Если статья описывает фильтр "
        "сигналов или ансамбль простых правил и способ получения направления очевиден из формул (например знак "
        "взвешенной суммы), это Strategy, а очевидное допущение запиши в formula_and_logic словом 'допущение'. "
        "Отсутствие теста вне выборки у автора не причина отказа. Причина отказа только фатальный порок: данные "
        "будущего, невозможность записать ни правило, ни признак, неприменимые данные, мартингейл или сетка, статья "
        "не про торговое правило и не про признак."
        + NOT_FAULTS +
        "Заполни checks: repaint (перерисовка и заглядывание вперёд) и "
        "higher_tf (значения старшего таймфрейма только по закрытому бару) со status 'нет' (проблемы нет), "
        "'исправимо' (заменяется закрытым баром, и в формуле это уже сделано) или 'неустранимо'; tick_volume со "
        "status 'не нужен' или 'нужен'; в каждом note - одна фраза. При неустранимом пороке вердикт REJECT. "
        "При PASS извлеки правило или признак строго по тексту, ничего не выдумывая; если параметр не назван, "
        "напиши, что он не указан. Каждое утверждение о правиле подтверди в source_quotes: от 2 до 6 объектов с "
        "ключами about (что подтверждает) и quote (фрагмент TEXT от 5 до 40 слов, скопированный буква в букву на "
        "языке статьи, без перевода, пересказа и пропусков). Цитаты бери только из TEXT, не из доводов адвоката и "
        "прокурора: программа проверит каждую по тексту статьи. Пиши по-русски. Ответ только JSON с ключами: "
        "verdict (PASS или REJECT), edge_type (Strategy или Feature_Or_Filter, пусто при REJECT), reject_reason "
        "(текст, пусто при PASS), formula_and_logic (точное описание), entry_long, entry_short, exit_rule, "
        "stop_rule (строкой, пусто если нет), feature_output, parameters (словарь имя и значение из статьи), "
        "timeframes (список), forex_pairs (список), checks (словарь repaint, higher_tf, tick_volume; значения - "
        "словари status и note), source_quotes (список), author_oos_metrics (строкой), summary (два предложения)."
    ),
}


OTHER_ROLES: Dict[str, str] = {}  # роли других программ (перевод спеки в правило); отпечаток жюри не меняют


def _system(role: str) -> str:
    return ROLES.get(role) or OTHER_ROLES[role]


def _read_key_file(name: str) -> str:
    """Ключ из локального файла рядом со скриптом (в репозиторий не попадает: см. .gitignore)."""
    try:
        with open(name, encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


OPENROUTER_MODEL = "z-ai/glm-5.3-flash"
REASONING_ROOM = 6000  # GLM всегда "думает", и эти токены входят в ответ: без запаса JSON обрывается


def model_id(cfg: Dict, model: str) -> str:
    """Имя связки для журнала и эталонной проверки: поставщик, рабочая модель и модель судьи."""
    if cfg.get("provider") != "openrouter":
        return model
    judge = cfg.get("judge_model") or model
    return "openrouter:" + model + ("" if judge == model else "+" + judge)


def accepted_versions() -> set:
    """Пары (отпечаток заданий, связка), прошедшие эталонный набор."""
    try:
        with open(ACCEPTED_PATH, encoding="utf-8") as f:
            return {tuple(line.split()[:2]) for line in f if len(line.split()) >= 2}
    except OSError:
        return set()


def _openrouter():
    key = os.getenv("OPENROUTER_API_KEY") or _read_key_file("openrouter_key.txt")
    if not key:
        return None
    worker = os.getenv("JURY_WORKER_MODEL") or OPENROUTER_MODEL
    return {"base": "https://openrouter.ai/api/v1", "key": key, "json_mode": True, "provider": "openrouter",
            "judge_model": os.getenv("JURY_JUDGE_MODEL") or worker}, worker, 20


def _client():
    """Возвращает (cfg, model, лимит_статей) или None. Без библиотеки openai: обычный HTTP.
    OpenRouter берётся сам только после того, как эта связка прошла эталонный набор с нынешними заданиями;
    JURY_PROVIDER=openrouter включает его принудительно (для самой эталонной проверки)."""
    want = (os.getenv("JURY_PROVIDER") or "").strip().lower()
    router = _openrouter()
    if want == "openrouter":
        return router
    if router and (prompt_sha(), model_id(router[0], router[1])) in accepted_versions():
        return router
    dash = os.getenv("DASHSCOPE_API_KEY") or _read_key_file("dashscope_key.txt")
    if dash:
        return {"base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "alt_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "key": dash, "json_mode": True}, "qwen-plus", 20
    if os.getenv("OPENAI_API_KEY"):
        return {"base": "https://api.openai.com/v1",
                "key": os.environ["OPENAI_API_KEY"], "json_mode": True}, "gpt-4o-mini", 20
    if os.getenv("GITHUB_TOKEN"):
        # GitHub Models: бесплатно, ключ не нужен, но есть дневные лимиты запросов
        return {"base": "https://models.github.ai/inference",
                "key": os.environ["GITHUB_TOKEN"], "json_mode": False}, os.getenv("JURY_MODEL", "openai/gpt-4o"), 5
    return None


MAX_TOKENS = {"advocate": 1500, "prosecutor": 1800, "judge": 6000}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def prompt_sha() -> str:
    """Отпечаток всех трёх заданий: меняется при любой правке их текста."""
    return _sha("\n".join(ROLES[r] for r in sorted(ROLES)))


def _trace(trace: Optional[Dict], role: str, base_url: str, body: Dict, response: str) -> None:
    """Строка журнала на каждое обращение к модели. Ключ сюда не попадает (он только в заголовке).
    Текст статьи заменён меткой с отпечатком: он уже лежит в файле кандидата."""
    if not trace:
        return
    request = json.loads(json.dumps(body))
    article = trace.get("article") or ""
    if article:
        mark = f"<<ТЕКСТ СТАТЬИ {trace.get('ref', '')} sha256={_sha(article)}>>"
        for m in request["messages"]:
            m["content"] = m["content"].replace(article, mark)
    os.makedirs(os.path.dirname(trace["path"]), exist_ok=True)
    with open(trace["path"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": trace.get("run"), "step": role,
                            "url": base_url, "model": body.get("model"), "system_sha": _sha(_system(role)),
                            "request": request, "response": response}, ensure_ascii=False) + "\n")


def _ask(cfg, model: str, role: str, content: str, trace: Optional[Dict] = None) -> Optional[Dict]:
    body = {"model": model, "temperature": 0.0, "max_tokens": MAX_TOKENS[role],
            "messages": [{"role": "system", "content": _system(role) + " Отвечай только JSON."},
                         {"role": "user", "content": content}]}
    if cfg.get("json_mode"):
        body["response_format"] = {"type": "json_object"}
    if cfg.get("provider") == "openrouter":
        if role == "judge" and cfg.get("judge_model"):
            body["model"] = cfg["judge_model"]
        body["reasoning"] = {"effort": os.getenv("JURY_REASONING") or "low"}
        body["max_tokens"] += REASONING_ROOM
        if body["model"].startswith("z-ai/"):
            # у модели десятки поставщиков с разным качеством: берём одного, чтобы эталонная проверка что-то значила
            body["provider"] = {"only": [os.getenv("JURY_OR_UPSTREAM") or "z-ai"], "allow_fallbacks": False}
    req = urllib.request.Request(
        cfg["base"] + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json",
                 "Accept": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=300 if cfg.get("provider") == "openrouter" else 120) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 401 and cfg.get("alt_base"):
            # ключ может быть от другого региона DashScope: пробуем второй адрес и запоминаем
            cfg["base"], cfg["alt_base"] = cfg["alt_base"], None
            _log("[JURY] 401 на первом адресе DashScope, пробую второй регион")
            return _ask(cfg, model, role, content, trace)
        detail = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
        _trace(trace, role, cfg["base"], body, detail)
        raise RuntimeError(detail)
    except OSError as e:
        _trace(trace, role, cfg["base"], body, f"сеть: {e}")
        raise
    _trace(trace, role, cfg["base"], body, raw)
    try:
        text = json.loads(raw)["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"неожиданный ответ сервера: {raw[:300]}")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    return json.loads(text)


def _ask_retry(cfg, model: str, role: str, content: str, trace: Optional[Dict] = None) -> Optional[Dict]:
    """Один повтор, если модель вернула битый JSON (например, оборванный ответ)."""
    try:
        return _ask(cfg, model, role, content, trace)
    except json.JSONDecodeError:
        _log(f"[JURY] битый JSON от роли {role}, повторяю один раз")
        return _ask(cfg, model, role, content, trace)


def _excerpt(t: str) -> str:
    """Статья целиком: параметры и логика лежат в середине текста, обрезать нельзя.
    Верхняя граница нужна только как защита от аномально длинного текста."""
    return t if len(t) <= 90000 else t[:50000] + "\n...\n" + t[-40000:]


def _plain(text: str) -> str:
    """Только слова и числа: регистр, знаки препинания и переносы строк не считаются."""
    return " ".join(re.findall(r"[^\W_]+", str(text).replace("\xad", "").lower().replace("ё", "е")))


def check_quotes(quotes, text: str) -> Dict:
    """Ищет каждую цитату судьи в тексте статьи. Короткие (меньше 4 слов) доказательством не считаются."""
    source = f" {_plain(text)} "
    found, missing = [], []
    for item in quotes if isinstance(quotes, list) else []:
        q = str(item.get("quote") if isinstance(item, dict) else item or "").strip()
        parts = [_plain(p) for p in re.split(r"\.\.\.|…", q)]
        parts = [p for p in parts if p]
        ok = (bool(parts) and sum(len(p.split()) for p in parts) >= 4
              and all(f" {p} " in source for p in parts))
        if ok and parts in [f[0] for f in found]:
            continue  # повтор той же цитаты
        if ok:
            found.append((parts, item))
        else:
            missing.append(q)
    return {"found": [f[1] for f in found], "missing": missing}


def _status(checks, name: str) -> str:
    v = checks.get(name) if isinstance(checks, dict) else None
    return str(v.get("status", "") if isinstance(v, dict) else v or "").strip().lower()


def check_pass(ver: Dict, text: str) -> Tuple[str, List[str], Dict]:
    """Проверка вердикта PASS программой: (фатальная причина, исправимые замечания, итог по цитатам)."""
    checks = ver.get("checks")
    bad = [n for n in ("repaint", "higher_tf") if _status(checks, n).startswith("неустран")]
    defects = []
    edge = str(ver.get("edge_type") or "").strip()
    if edge not in EDGE_TYPES:
        defects.append("edge_type должен быть Strategy или Feature_Or_Filter")
    if len(str(ver.get("formula_and_logic") or "").strip()) < 20:
        defects.append("PASS без формулы")
    if edge == "Strategy" and not any(len(str(ver.get(k) or "").strip()) >= 10 for k in ("entry_long", "entry_short")):
        defects.append("Strategy без условия входа")
    if edge == "Feature_Or_Filter" and len(str(ver.get("feature_output") or "").strip()) < 10:
        defects.append("Feature_Or_Filter без описания величины в feature_output")
    empty = [n for n in CHECK_NAMES if not _status(checks, n)]
    if empty:
        defects.append("не заполнены checks: " + ", ".join(empty))
    quotes = check_quotes(ver.get("source_quotes"), text)
    if len(quotes["found"]) < MIN_QUOTES:
        lost = "; ".join(q[:120] for q in quotes["missing"][:6])
        defects.append(f"в TEXT подтверждено цитат: {len(quotes['found'])}, нужно не меньше {MIN_QUOTES}"
                       + (f"; не найдены дословно: {lost}" if lost else ""))
    fatal = ("неустранимая проблема по проверке: " + ", ".join(bad)) if bad else ""
    return fatal, defects, quotes


def _verdict(ver) -> str:
    v = str(ver.get("verdict", "")).upper() if isinstance(ver, dict) else ""
    if v not in ("PASS", "REJECT"):
        raise ValueError("bad verdict")
    return v


def judge_article(client, model: str, d: Dict, trace: Optional[Dict] = None) -> Tuple[str, Dict]:
    """Суд над одной статьёй: (PASS или REJECT, всё, что сказали роли и проверила программа)."""
    article = _excerpt(d["text"])
    if trace is not None:
        trace["article"] = article
    base = f"TITLE: {d['title']}\nYEAR: {d.get('published_year')}\n\nTEXT:\n{article}"
    adv = _ask_retry(client, model, "advocate", base, trace)
    pro = _ask_retry(client, model, "prosecutor", base, trace)
    case = base + f"\n\nADVOCATE: {json.dumps(adv, ensure_ascii=False)}\nPROSECUTOR: {json.dumps(pro, ensure_ascii=False)}"
    ver = _ask_retry(client, model, "judge", case, trace)
    verdict, check, first = _verdict(ver), None, []
    if verdict == "PASS":
        fatal, defects, quotes = check_pass(ver, d["text"])
        first = list(defects)
        if defects and not fatal:
            _log("[JURY] замечания программы, судья переспрошен: " + "; ".join(defects)[:300])
            ver = _ask_retry(client, model, "judge", case + "\n\nПРОГРАММА ПРОВЕРИЛА ТВОЙ ПРОШЛЫЙ ОТВЕТ PASS И НЕ ПРИНЯЛА: "
                             + "; ".join(defects) + ". Дай исправленный ответ целиком. Если подтвердить текстом "
                             "статьи нельзя, вынеси REJECT.", trace)
            verdict = _verdict(ver)
            if verdict == "PASS":
                fatal, defects, quotes = check_pass(ver, d["text"])
        if verdict == "PASS":
            check = {"confirmed": len(quotes["found"]), "unconfirmed": quotes["missing"], "first_remarks": first}
            ver["source_quotes"] = quotes["found"]  # неподтверждённые цитаты в правило не идут
            if fatal or defects:
                verdict = "REJECT"
                ver["verdict"] = "REJECT"
                ver["reject_reason"] = "программа не приняла PASS: " + "; ".join(([fatal] if fatal else []) + defects)
    result = {"advocate": adv, "prosecutor": pro, "judge": ver, "model": model_id(client, model), "prompt_sha": prompt_sha(),
              "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    if check:
        result["program_check"] = check
    elif verdict == "REJECT" and first:
        result["program_check"] = {"first_remarks": first}
    return verdict, result


def dedupe_passed() -> int:
    """Убирает повторы строк одной статьи (по url) из passed_edges.jsonl. Возвращает число убранных."""
    if not os.path.exists(PASSED_PATH):
        return 0
    seen, keep, removed = set(), [], 0
    with open(PASSED_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                u = json.loads(line).get("url")
            except ValueError:
                keep.append(line)
                continue
            if u in seen:
                removed += 1
                continue
            seen.add(u)
            keep.append(line)
    if removed:
        with open(PASSED_PATH, "w", encoding="utf-8") as fh:
            fh.write("\n".join(keep) + "\n")
        _log(f"[JURY] убрано повторов в passed_edges.jsonl: {removed}")
    return removed


def _already_passed(url: str) -> bool:
    if not os.path.exists(PASSED_PATH):
        return False
    with open(PASSED_PATH, encoding="utf-8") as fh:
        return any(f'"url": "{url}"' in line for line in fh)


def run_pending() -> None:
    dedupe_passed()
    files = sorted(glob.glob(os.path.join(CAND_DIR, "*.json")))
    pending = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("status") == "pending" or (os.getenv("XGB_REJUDGE") == "1" and d.get("status") == "rejected"):
            pending.append((f, d))
    _log(f"[JURY] в очереди: {len(pending)}")
    if not pending:
        return
    cl = _client()
    if cl is None:
        _log("[JURY] ключа нет - суд пропущен, кандидаты ждут. Сбор статей не затронут.")
        return
    client, model, default_limit = cl
    limit = JURY_LIMIT or default_limit
    done = 0
    run_id = time.strftime("%Y%m%d-%H%M%S")
    for f, d in pending[:limit]:
        try:
            name = os.path.splitext(os.path.basename(f))[0]
            trace = {"path": os.path.join(RAW_DIR, name + ".jsonl"), "run": run_id, "ref": "candidates/" + name + ".json"}
            verdict, result = judge_article(client, model, d, trace)
            ver = result["judge"]
            old = d.get("jury")
            new_status = "passed" if verdict == "PASS" else "rejected"
            if old:
                result["previous"] = {"status": d.get("status"), "model": old.get("model"),
                                      "prompt_sha": old.get("prompt_sha")}
                if d.get("status") != new_status:
                    same = ("задания те же" if old.get("prompt_sha") == result["prompt_sha"]
                            else "задания изменились" if old.get("prompt_sha") else "прежние задания без отпечатка")
                    _log(f"[JURY] вердикт изменился: {d.get('status')} -> {new_status} ({same}, "
                         f"модель {old.get('model') or 'не записана'} -> {model}): {d['title']}")
            d["status"] = new_status
            d["jury"] = result
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            if verdict == "PASS" and not _already_passed(d["url"]):
                with open(PASSED_PATH, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"url": d["url"], "title": d["title"],
                                         "published_year": d.get("published_year"), **ver},
                                        ensure_ascii=False) + "\n")
            if verdict == "PASS":
                os.makedirs(SPEC_DIR, exist_ok=True)
                with open(os.path.join(SPEC_DIR, os.path.basename(f)), "w", encoding="utf-8") as fh:
                    json.dump({"url": d["url"], "title": d["title"], "published_year": d.get("published_year"), **ver},
                              fh, ensure_ascii=False, indent=1)
            kind = f" [{ver.get('edge_type')}]" if verdict == "PASS" else ""
            _log(f"[JURY] {verdict}{kind}: {d['title']}")
            done += 1
            time.sleep(PAUSE_SEC)
        except Exception as e:
            _log(f"[JURY] сбой на {d.get('url')}: {e} - останется в очереди")
            if "HTTP 402" in str(e):
                _log("[JURY] на счёте поставщика нет средств - остановка")
                break
            if "HTTP 429" in str(e) or "rate limit" in str(e).lower():
                _log("[JURY] лимит запросов исчерпан - остановка, продолжим в следующий запуск")
                break
    _log(f"[JURY] обработано: {done}")


if __name__ == "__main__":
    run_pending()
