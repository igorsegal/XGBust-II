"""Фильтр 1: без модели и без интернета. Никогда не падает."""
import re
from typing import Optional

TITLE_STOP = [
    "gui", "canvas", "cairo", "telegram", "sftp", "watchdog", "panel", "dashboard",
    "webrequest", "sqlite", "database", "websocket", "library for", "table",
    "market depth", "order book", "cryptocurrenc", "bitcoin", "stock market",
    "grid expert", "grid ea", "martingale", "files", "json", "http", "css", "html", "docker", "onnx model deployment",
]
EDGE_WORDS = [
    "indicator", "signal", "entry", "exit", "strategy", "feature", "regime",
    "volatility", "forecast", "predict", "classif", "xgboost", "gradient boost",
    "correlation", "momentum", "trend", "mean reversion", "filter",
]
# Свидетельства того, что статья что-то проверяла на рынке (мягкий список)
PROOF_WORDS = [
    "backtest", "back-test", "strategy tester", "profit factor", "drawdown",
    "sharpe", "expectancy", "out-of-sample", "walk-forward", "win rate", "net profit",
    "test results", "testing results", "tested", "trades", "profit", "balance curve",
    "equity", "recovery factor", "historical data", "training period", "test period",
]
# Торговая сетка / мартингейл. Слово "grid" само по себе не считаем: "grid search" и т.п.
GRID_PATTERNS = r"martingale|averaging down|grid trading|grid strategy|grid expert|grid of (?:pending )?orders|order grid|grid system|grid ea\b"
MIN_TEXT = 3000


def prefilter(article: dict) -> Optional[str]:
    """None = пропустить дальше (кандидат). Строка = причина отказа."""
    title = (article.get("title") or "").lower()
    text = (article.get("text") or "").lower()
    if len(text) < MIN_TEXT:
        return "short_text"
    for w in TITLE_STOP:
        if re.search(r"\b" + re.escape(w), title):
            return f"title:{w}"
    if len(re.findall(GRID_PATTERNS, text)) >= 4:
        return "martingale_grid"
    if sum(text.count(w) for w in EDGE_WORDS) < 8:
        return "no_trading_logic"
    if sum(text.count(w) for w in PROOF_WORDS) + text.count("test") < 5:
        return "no_test_results"
    return None


def stats(article: dict) -> str:
    """Числа, по которым принято решение: для настройки порогов."""
    text = (article.get("text") or "").lower()
    edge = sum(text.count(w) for w in EDGE_WORDS)
    proof = sum(text.count(w) for w in PROOF_WORDS)
    grid = len(re.findall(GRID_PATTERNS, text))
    return f"len={len(text)} edge={edge} proof={proof} test={text.count('test')} grid={grid}"
