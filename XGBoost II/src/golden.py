"""Эталонный набор: статьи с заранее известным вердиктом. Запускать после любой правки заданий жюри,
смены модели или поставщика:  python -m src.golden
Кандидатов, passed_edges.jsonl и specs не трогает.

Замок: новые задания считаются принятыми, только если все статьи набора (не меньше 10) оценены верно -
тогда их отпечаток пишется в accepted.txt. python -m src.golden --check без запросов к модели отвечает,
принята ли нынешняя версия (код 0 - да, 1 - нет); кнопка отправки на GitHub без этого jury.py не берёт."""
import glob
import json
import os
import sys
import time

try:
    from src import jury
except ImportError:
    import jury

GOLDEN_DIR = os.getenv("XGB_GOLDEN") or os.path.join(jury.DATA_DIR, "golden")
OUT_DIR = os.getenv("XGB_GOLDEN_OUT") or os.path.join(jury.DATA_DIR, "golden_runs")
ACCEPTED = jury.ACCEPTED_PATH
MIN_ARTICLES = 10
DEFAULT_MODEL = "qwen-plus"  # на нём жюри работает, если другая связка не принята


def record(sha: str, model: str, line: str) -> None:
    """Переписывает строку этой пары (задания, модель): пустая line - принятие отозвано."""
    try:
        with open(ACCEPTED, encoding="utf-8") as fh:
            rows = [r for r in fh.read().splitlines() if r.split() and r.split()[:2] != [sha, model]]
    except OSError:
        rows = []
    os.makedirs(os.path.dirname(ACCEPTED), exist_ok=True)
    with open(ACCEPTED, "w", encoding="utf-8") as fh:
        fh.write("".join(r + "\n" for r in rows + ([line] if line else [])))


def check_accepted() -> int:
    sha = jury.prompt_sha()
    if (sha, DEFAULT_MODEL) in jury.accepted_versions():
        print(f"[GOLDEN] задания {sha} приняты эталонным набором")
        return 0
    print(f"[GOLDEN] задания {sha} НЕ приняты эталонным набором: запустите python -m src.golden")
    return 1


def compare(expected: dict, verdict: str, result: dict) -> str:
    """Пустая строка - совпало, иначе в чём расхождение."""
    if verdict != expected["verdict"]:
        return f"ждали {expected['verdict']}, получили {verdict}"
    want = expected.get("edge_type")
    got = str(result["judge"].get("edge_type") or "")
    if want and verdict == "PASS" and got != want:
        return f"ждали вид {want}, получили {got}"
    return ""


def run() -> int:
    files = sorted(glob.glob(os.path.join(GOLDEN_DIR, "*.json")))
    if not files:
        print(f"[GOLDEN] нет статей в {GOLDEN_DIR}")
        return 2
    cl = jury._client()
    if cl is None:
        print("[GOLDEN] нет ключа жюри")
        return 2
    client, model, _ = cl
    name_of_model = jury.model_id(client, model)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = [f"Эталонный набор {run_id}, модель {name_of_model}, отпечаток заданий {jury.prompt_sha()}"]
    right = failed = 0
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        trace = {"path": os.path.join(OUT_DIR, "raw", name + ".jsonl"), "run": run_id, "ref": "golden/" + name + ".json"}
        try:
            verdict, result = jury.judge_article(client, model, d, trace)
        except Exception as e:
            failed += 1
            lines.append(f"СБОЙ  {name}: {e}")
            print(lines[-1], flush=True)
            if "HTTP 429" in str(e) or "HTTP 402" in str(e):
                break
            continue
        diff = compare(d["expected"], verdict, result)
        right += not diff
        why = str(result["judge"].get("reject_reason") or "")[:300]
        lines.append(f"{'ВЕРНО ' if not diff else 'ОШИБКА'} {name}: {verdict} {result['judge'].get('edge_type') or ''} "
                     f"| {d['title'][:70]}" + (f" | {diff} | {why}" if diff else ""))
        print(lines[-1], flush=True)
        time.sleep(jury.PAUSE_SEC)
    lines.append(f"ИТОГ: верно {right} из {len(files)}, сбоев {failed}")
    print(lines[-1])
    with open(os.path.join(OUT_DIR, "last_result.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(OUT_DIR, "history.txt"), "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n\n")
    sha = jury.prompt_sha()
    if right == len(files) >= MIN_ARTICLES:
        record(sha, name_of_model, f"{sha} {name_of_model} {run_id} верно {right} из {len(files)}")
        print(f"[GOLDEN] принято: задания {sha}, модель {name_of_model}")
    else:
        if not failed:  # настоящие расхождения отзывают прежнее принятие, обрыв связи - нет
            record(sha, name_of_model, "")
        print(f"[GOLDEN] версия НЕ принята (модель {name_of_model}): исправьте задания или оставьте прежнюю связку")
    return 0 if right == len(files) else 1


if __name__ == "__main__":
    sys.exit(check_accepted() if "--check" in sys.argv[1:] else run())
