# -*- coding: utf-8 -*-
"""Достраивает D:\\BAZA: чего нет в наборе Hugging Face, берётся прямо из Dukascopy (часовые файлы .bi5).

XAUUSD пересобирается с недостающими днями, USDJPY и AUDUSD собираются целиком. Прерванную загрузку
можно запускать снова: скачанное лежит в D:\\BAZA\\_cache и стирается после сборки инструмента.
"""
import datetime as dt
import lzma
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import build_baza as b

q = b.q
DUKAS = "https://datafeed.dukascopy.com/datafeed"
# инструмент -> (знаков после запятой, нужно свободного места, ГБ); порядок = порядок работы
SYMBOLS = {"XAUUSD": (3, 16), "USDJPY": (3, 12), "AUDUSD": (5, 10)}
BI5 = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"), ("ask_volume", ">f4"), ("bid_volume", ">f4")])
WORKERS, PAUSE, ATTEMPTS = 4, 0.2, 6
EPOCH = dt.datetime(1970, 1, 1)
DAY = dt.timedelta(days=1)


def decode(data):
    if not data:
        return np.empty(0, BI5)
    raw = lzma.decompress(data)
    if len(raw) % BI5.itemsize:
        raise ValueError("повреждённый часовой файл")
    return np.frombuffer(raw, BI5)


def fetch_hour(symbol, t):
    """Содержимое часового файла; b'' если в этот час тиков нет."""
    url = f"{DUKAS}/{symbol}/{t.year}/{t.month - 1:02d}/{t.day:02d}/{t.hour:02d}h_ticks.bi5"
    for attempt in range(ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
                length = r.headers.get("Content-Length")
            if length is not None and int(length) != len(data):
                raise OSError("файл получен не полностью")
            decode(data)
            time.sleep(PAUSE)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            error = f"HTTP {e.code}"
        except Exception as e:
            error = str(e) or type(e).__name__
        if attempt < ATTEMPTS - 1:
            time.sleep(2 * 2 ** attempt)
    raise OSError(error)


def hours(first, last):
    t, stop = dt.datetime.combine(first, dt.time()), dt.datetime.combine(last, dt.time(23))
    while t <= stop:
        if t.weekday() != 5:                              # суббота: рынок закрыт
            yield t
        t += dt.timedelta(hours=1)


def hour_file(folder, t):
    return folder / f"{t:%Y-%m-%d_%H}.bi5"


def download_hours(symbol, folder, todo):
    folder.mkdir(parents=True, exist_ok=True)
    todo = [t for t in todo if not hour_file(folder, t).is_file()]
    print(f"{symbol}: из Dukascopy нужно скачать часов: {len(todo)}", flush=True)

    def one(t):
        try:
            data = fetch_hour(symbol, t)
        except OSError as e:
            return t, str(e)
        part = folder / f"{t:%Y-%m-%d_%H}.part"
        part.write_bytes(data)
        os.replace(part, hour_file(folder, t))
        return t, None

    failed, bad_batches, started = [], 0, time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i in range(0, len(todo), 100):
            result = list(pool.map(one, todo[i:i + 100]))
            errors = [(t, e) for t, e in result if e]
            failed += errors
            done = i + len(result)
            left = (time.time() - started) / done * (len(todo) - done) / 60
            print(f"{symbol} {done}/{len(todo)}  {result[-1][0]:%Y-%m-%d}  ошибок: {len(failed)}  "
                  f"осталось около {left:.0f} мин", flush=True)
            bad_batches = bad_batches + 1 if len(errors) > len(result) // 2 else 0
            if bad_batches >= 3:
                raise SystemExit("STOP: Dukascopy не отвечает. Запустите этот же файл позже.")
    for t, _ in list(failed):                             # второй заход по ошибкам
        t, error = one(t)
        if not error:
            failed = [x for x in failed if x[0] != t]
    if failed:
        raise SystemExit(f"STOP: не скачано часов: {len(failed)} (первый {failed[0][0]:%Y-%m-%d %H}h, "
                         f"{failed[0][1]}). Запустите этот же файл ещё раз.")


def read_hours(folder, symbol_scale, volume_factor, first, last):
    """Тики отрезка в тех же колонках, что и parquet."""
    out = {c: [] for c in q.COLUMNS}
    for t in hours(first, last):
        a = decode(hour_file(folder, t).read_bytes())
        if not len(a):
            continue
        start = int((t - EPOCH).total_seconds()) * 1000
        out["timestamp"].append(start + a["ms"].astype(np.int64))
        out["askPrice"].append(a["ask"] / symbol_scale)
        out["bidPrice"].append(a["bid"] / symbol_scale)
        out["askVolume"].append(a["ask_volume"].astype(np.float64) * volume_factor)
        out["bidVolume"].append(a["bid_volume"].astype(np.float64) * volume_factor)
    return {c: np.concatenate(v) if v else np.empty(0, np.int64 if c == "timestamp" else np.float64)
            for c, v in out.items()}


def compare(parquet, symbol, scale, day):
    """Один и тот же час из набора и из Dukascopy обязан совпасть. Возвращает множитель объёма."""
    ts = np.asarray(parquet["timestamp"], dtype=np.int64)
    for offset in range(0, 240):
        t = dt.datetime.combine(day, dt.time(8)) + dt.timedelta(hours=offset)
        start = int((t - EPOCH).total_seconds()) * 1000
        pick = (ts >= start) & (ts < start + 3600_000)
        if pick.sum() < 100:
            continue
        a = decode(fetch_hour(symbol, t))
        n = int(pick.sum())
        same = (len(a) == n
                and (start + a["ms"].astype(np.int64) == ts[pick]).all()
                and (a["bid"] == np.rint(np.asarray(parquet["bidPrice"])[pick] * scale)).all()
                and (a["ask"] == np.rint(np.asarray(parquet["askPrice"])[pick] * scale)).all())
        if not same:
            raise SystemExit(f"STOP: {symbol} {t:%Y-%m-%d %H}h не совпал: в наборе {n} тиков, в Dukascopy {len(a)}"
                             + (f", первая цена {np.asarray(parquet['bidPrice'])[pick][0]} / {a['bid'][0]}" if len(a) else ""))
        mine, theirs = a["bid_volume"].astype(float), np.asarray(parquet["bidVolume"], float)[pick]
        factor = float(np.median(theirs[mine > 0] / mine[mine > 0]))
        factor = float(f"{factor:.4g}")
        if not np.allclose(mine * factor, theirs, rtol=1e-3, atol=1e-9):
            raise SystemExit(f"STOP: {symbol}: объёмы набора и Dukascopy не сопоставляются")
        print(f"{symbol}: сверка с Dukascopy за {t:%Y-%m-%d %H}h совпала ({n} тиков, множитель объёма {factor:g})")
        return factor
    raise SystemExit(f"STOP: {symbol}: не нашёлся час для сверки")


def segments(ranges):
    """Режет недостающие отрезки на куски не длиннее 30 дней."""
    for a, z in ranges:
        while a <= z:
            e = min(a + 29 * DAY, z)
            yield a, e
            a = e + DAY


def build_symbol(symbol, digits, files):
    chosen, gaps = b.cover(files)
    last_hf = dt.date.fromisoformat(chosen[-1][0].split("_")[1])
    if last_hf < q.LAST_DAY:
        gaps.append((last_hf + DAY, q.LAST_DAY))
    cache = b.OUT / "_cache" / symbol
    bi5 = cache / "bi5"
    cache.mkdir(parents=True, exist_ok=True)
    scale = 10 ** digits

    # сверка по первому файлу набора (он потом пригодится сборке)
    first, day = chosen[0]
    kept = cache / f"{first}.parquet"
    if not (kept.is_file() and kept.stat().st_size == files[first]):
        base = f"https://huggingface.co/datasets/{b.REPO}/resolve/main/data/{symbol}"
        b.download(base, first, cache)
    factor = compare(q.read_parquet(kept), symbol, scale, day)

    own = {f"{a}_{z}": (a, z) for a, z in segments(gaps)}
    download_hours(symbol, bi5, [t for a, z in own.values() for t in hours(a, z)])

    def fetcher(base_url, name, folder):
        if name not in own:
            return b.download(base_url, name, folder)
        path = folder / f"{name}.parquet"
        path.write_bytes(b"D")                            # метка: данные лежат в bi5
        return path

    def reader(path):
        if path.stem in own:
            return read_hours(bi5, scale, factor, *own[path.stem])
        return q.read_parquet(path)

    merged = {**files, **{n: 1 for n in own}}
    (b.OUT / symbol / "REPORT.txt").unlink(missing_ok=True)
    price, left, last = b.build_symbol(symbol, digits, merged, reader, fetcher)
    with open(b.OUT / symbol / "REPORT.txt", "a", encoding="utf-8") as f:
        f.write("- Взято напрямую из Dukascopy: " + (", ".join(f"{a}..{z}" for a, z in gaps) or "ничего") + "\n")
    return price, last


def main():
    done = []
    for symbol, (digits, need) in SYMBOLS.items():
        report = b.OUT / symbol / "REPORT.txt"
        if report.is_file() and "из Dukascopy" in report.read_text(encoding="utf-8"):
            done.append(f"{symbol}: уже готов")
            continue
        b.OUT.mkdir(parents=True, exist_ok=True)
        have = sum(p.stat().st_size for d in (b.OUT / symbol, b.OUT / "_cache" / symbol) if d.is_dir()
                   for p in d.rglob("*") if p.is_file())
        free = shutil.disk_usage(b.OUT).free + have
        if free < need * 1024 ** 3:
            print(f"STOP: NOT ENOUGH SPACE for {symbol}: free {free / 1024 ** 3:.1f} GB, need {need} GB.")
            return 1
        print(f"=== {symbol}", flush=True)
        price, last = build_symbol(symbol, digits, b.list_files(symbol))
        done.append(f"{symbol}: OK, до {last}, цена {price[0]:.{digits}f}..{price[1]:.{digits}f}")
    print("\n" + "\n".join(done))
    print("BAZA DUKAS OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
