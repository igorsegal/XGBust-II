# -*- coding: utf-8 -*-
"""Единая база D:\\BAZA\\<инструмент> из набора mito0o852/dukascopy-ticks (тот же расчёт, что для EURUSD).

Ничего старого не изменяет и не удаляет. Прерванную загрузку можно запустить снова:
уже скачанные файлы берутся из D:\\BAZA\\_cache и стираются после сборки инструмента.
"""
import datetime as dt
import json
import os
import re
import shutil
import struct
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import build_quotes as q

OUT = Path("D:/AHexaTrader/1DataFiles/BAZA")
REPO = "mito0o852/dukascopy-ticks"
# инструмент -> (знаков после запятой, нужно свободного места, ГБ)
SYMBOLS = {"GBPUSD": (5, 12), "XAUUSD": (3, 20)}
download = q.fetch
make_report = q.make_report


def list_files(symbol):
    """Имена и размеры всех файлов инструмента."""
    url = f"https://huggingface.co/api/datasets/{REPO}/tree/main/data/{symbol}"
    files = {}
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "xgboost-edge"})
        with urllib.request.urlopen(req, timeout=120) as r:
            for f in json.load(r):
                if f["path"].endswith(".parquet"):
                    files[f["path"].rsplit("/", 1)[1][:-8]] = f.get("lfs", f)["size"]
            m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
        url = m.group(1) if m else None
    return files


def cover(names):
    """Выбирает файлы без повторов. Возвращает [(имя, первый новый день)] и список пропусков."""
    spans = sorted((tuple(map(dt.date.fromisoformat, n.split("_"))), n) for n in names)
    day = dt.timedelta(days=1)
    chosen, gaps, cursor = [], [], q.FIRST_DAY
    while True:
        left = [(b, a, n) for (a, b), n in spans if b >= cursor]
        if not left:
            return chosen, gaps
        now = [x for x in left if x[1] <= cursor]
        if not now:                                       # в наборе дыра
            nxt = min(x[1] for x in left)
            gaps.append((cursor, nxt - day))
            cursor = nxt
            continue
        end, _, name = max(now)                           # тот, что кончается позже всех
        chosen.append((name, cursor))
        cursor = end + day


def save_xfbar(path, m, period):
    rec = np.empty(len(m["time"]), q.BAR_DTYPE)
    for k in ("time", "open", "high", "low", "close", "tick_volume", "real_volume"):
        rec[k] = m[k]
    rec["spread"] = np.floor(m["spread_sum"] / m["tick_volume"] + 0.5)
    sym = q.SYMBOL.encode()
    digits = round(-np.log10(q.POINT))
    with open(path, "wb") as f:
        f.write(struct.pack("<8siiiidqqqi", b"XFBAR001", 1, 60, period, digits, q.POINT, len(rec),
                            int(rec["time"][0]), int(rec["time"][-1]), len(sym)) + sym)
        rec.tofile(f)


def build_symbol(symbol, digits, files, reader=None, fetcher=None):
    reader, fetcher = reader or q.read_parquet, fetcher or download
    chosen, gaps = cover(files)
    cut = {n: (d - dt.date(1970, 1, 1)).days * 86400_000 for n, d in chosen}
    last = dt.date.fromisoformat(chosen[-1][0].split("_")[1])
    cache = OUT / "_cache" / symbol
    cache.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OUT / "_download", ignore_errors=True)        # обрывки прерванного запуска
    price = [float("inf"), 0.0]

    def fetch(base_url, name, folder):
        kept = cache / f"{name}.parquet"
        if not (kept.is_file() and kept.stat().st_size == files[name]):
            part = fetcher(base_url, name, folder)
            os.replace(part, kept)
        target = folder / f"{name}.parquet"
        target.unlink(missing_ok=True)
        try:
            os.link(kept, target)                         # сборка удаляет только эту ссылку
        except OSError:
            shutil.copyfile(kept, target)
        return target

    def read(path):
        data = reader(path)
        keep = np.asarray(data["timestamp"], dtype=np.int64) >= cut[path.stem]
        data = {k: np.asarray(v)[keep] for k, v in data.items()}
        bid = data["bidPrice"][data["bidPrice"] > 0]
        if len(bid):
            price[0], price[1] = min(price[0], bid.min()), max(price[1], bid.max())
        return data

    def report(*args):
        text = make_report(*args).replace("кратных 0.00001", f"кратных {q.POINT:.{digits}f}")
        text += "\n## Источник\n\n"
        text += f"- Цена Bid от {price[0]:.{digits}f} до {price[1]:.{digits}f}\n"
        text += "- Дыры в наборе: " + (", ".join(f"{a}..{b}" for a, b in gaps) or "нет") + "\n"
        return text

    q.SYMBOL, q.POINT, q.SCALE = symbol, 10.0 ** -digits, 10 ** digits
    q.POINT = round(q.POINT, digits)
    q.chunk_names = lambda first, last: [n for n, _ in chosen]
    q.save_xfbar, q.fetch, q.make_report = save_xfbar, fetch, report
    base = f"https://huggingface.co/datasets/{REPO}/resolve/main/data/{symbol}"
    folder = OUT / symbol
    q.build(base, OUT, folder / "REPORT.tmp", q.FIRST_DAY, last, read)
    os.replace(folder / "REPORT.tmp", folder / "REPORT.txt")        # знак: инструмент готов
    shutil.rmtree(cache)
    return price, gaps, last


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    for symbol, (digits, need) in SYMBOLS.items():
        if (OUT / symbol / "REPORT.txt").is_file():
            done.append(f"{symbol}: уже готов")
            continue
        have = sum(p.stat().st_size for d in (OUT / symbol, OUT / "_cache" / symbol) if d.is_dir()
                   for p in d.rglob("*") if p.is_file())
        free = shutil.disk_usage(OUT).free + have
        if free < need * 1024 ** 3:
            print(f"STOP: NOT ENOUGH SPACE for {symbol}: free {free / 1024 ** 3:.1f} GB, need {need} GB.")
            return 1
        files = list_files(symbol)
        print(f"=== {symbol}: файлов в наборе {len(files)}", flush=True)
        price, gaps, last = build_symbol(symbol, digits, files)
        done.append(f"{symbol}: OK, до {last}, цена {price[0]:.{digits}f}..{price[1]:.{digits}f}, дыр {len(gaps)}")
    print("\n" + "\n".join(done))
    print("BAZA OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
