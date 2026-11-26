import glob
import json
import os
import re
import time

try:
    from src.scraper import append_seen_url, collect_batch, save_cursor
    from src.prefilter import prefilter, stats
    from src.jury import run_pending, CAND_DIR
except ImportError:
    from scraper import append_seen_url, collect_batch, save_cursor
    from prefilter import prefilter, stats
    from jury import run_pending, CAND_DIR

REJECTED_LOG = os.path.join(os.getenv("XGB_DATA", "data"), "rejected.tsv")


def _article_id(url: str) -> str:
    m = re.search(r"/articles/(\d+)", url)
    return m.group(1) if m else re.sub(r"\W+", "_", url)[-60:]


def save_candidate(art: dict) -> None:
    os.makedirs(CAND_DIR, exist_ok=True)
    with open(os.path.join(CAND_DIR, _article_id(art["url"]) + ".json"), "w", encoding="utf-8") as f:
        json.dump({**art, "status": "pending"}, f, ensure_ascii=False)


def log_rejected(art: dict, reason: str) -> None:
    os.makedirs(os.path.dirname(REJECTED_LOG), exist_ok=True)
    with open(REJECTED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{art['url']}\t{reason}\t{art['title']}\t{stats(art)}\n")
    if os.getenv("XGB_DATA", "data") != "data":  # тестовый режим: тексты отсеянных тоже сохраняем
        d = os.path.join(os.path.dirname(REJECTED_LOG), "rejected_texts")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, _article_id(art["url"]) + ".json"), "w", encoding="utf-8") as f:
            json.dump({**art, "reason": reason}, f, ensure_ascii=False)


def _status_path() -> str:
    return os.path.join(os.getenv("XGB_DATA", "data"), "last_run.json")


def _write_status(d: dict) -> None:
    os.makedirs(os.path.dirname(_status_path()), exist_ok=True)
    tmp = _status_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _status_path())  # файл появляется целиком, не наполовину


def _queue_counts() -> dict:
    out = {"pending": 0, "passed": 0, "rejected": 0}
    for f in glob.glob(os.path.join(CAND_DIR, "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                out[json.load(fh).get("status", "pending")] += 1
        except Exception:
            pass
    return out


def run() -> None:
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    status = {"status": "running", "started_utc": started, "batch": os.getenv("XGB_BATCH", "15")}
    _write_status(status)
    try:
        stats_run = _run_inner()
        status.update({"status": "finished", **stats_run})
    except BaseException as e:  # сбой тоже фиксируем
        status.update({"status": "error", "error": f"{type(e).__name__}: {e}"})
        raise
    finally:
        status["finished_utc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        status["queue"] = _queue_counts()
        _write_status(status)
        with open(os.path.join(os.getenv("XGB_DATA", "data"), "runs.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(status, ensure_ascii=False) + "\n")


def _run_inner() -> dict:
    print("Сбор статей MQL5 (фильтр 1 без модели, суд - отдельным шагом)")
    articles, next_cursor = collect_batch()
    print(f"Собрано статей: {len(articles)}")
    kept = 0
    for art in articles:
        reason = prefilter(art)
        if reason:
            log_rejected(art, reason)
            print(f"  [ОТСЕЯНА: {reason}] {art['published_year']} | {art['title'][:70]} | {stats(art)} | {art['url']}")
        else:
            save_candidate(art)
            kept += 1
            print(f"  [В ОЧЕРЕДЬ СУДА] {art['published_year']} | {art['title'][:70]} | {stats(art)} | {art['url']}")
        append_seen_url(art["url"])
    # Курсор двигается всегда: от модели он не зависит.
    save_cursor(next_cursor)
    print(f"Отсеяно фильтром 1: {len(articles) - kept}, в очередь суда: {kept}. Курсор сохранён: {next_cursor}")
    try:
        run_pending()
    except Exception as e:
        print(f"[JURY] неожиданный сбой, сбор не затронут: {e}")
    return {"collected": len(articles), "dropped_by_filter1": len(articles) - kept,
            "sent_to_jury_queue": kept, "blocked": bool(next_cursor.get("blocked_utc")), "cursor": next_cursor}


if __name__ == "__main__":
    run()
