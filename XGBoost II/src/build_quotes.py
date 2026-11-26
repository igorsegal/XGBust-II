# -*- coding: utf-8 -*-
"""База котировок EURUSD из набора mito0o852/dukascopy-ticks (Hugging Face).

Выход:
  <out>/EURUSD/EURUSD_<TF>.bin               бары XFBAR001 (формат тестера), время UTC, цены Bid
  <out>/EURUSD/ticks/EURUSD_ticks_<год>.bin  тики: заголовок 64 байта EQTICK01, запись 24 байта
  <report>                                   отчёт о проверке и пропусках
"""
import argparse
import collections
import datetime as dt
import os
import struct
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

SYMBOL = "EURUSD"
BASE_URL = "https://huggingface.co/datasets/mito0o852/dukascopy-ticks/resolve/main/data/" + SYMBOL
FIRST_DAY = dt.date(2016, 1, 1)
LAST_DAY = dt.date(2026, 5, 1)
POINT = 0.00001
SCALE = 100000
# имя -> (период в секундах, сдвиг начала); неделя начинается в воскресенье 00:00 UTC.
# В D1 короткий воскресный вечер входит в бар понедельника.
TIMEFRAMES = {
    "M1": (60, 0), "M5": (300, 0), "M15": (900, 0), "M30": (1800, 0),
    "H1": (3600, 0), "H4": (14400, 0), "D1": (86400, 0), "W1": (604800, 3 * 86400),
}
TICK_DTYPE = np.dtype([("time_ms", "<i8"), ("bid", "<i4"), ("ask", "<i4"),
                       ("bid_volume", "<f4"), ("ask_volume", "<f4")])
BAR_DTYPE = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
                      ("close", "<f8"), ("tick_volume", "<i8"), ("spread", "<i4"),
                      ("real_volume", "<i8")])
assert TICK_DTYPE.itemsize == 24 and BAR_DTYPE.itemsize == 60
COLUMNS = ("timestamp", "askPrice", "bidPrice", "askVolume", "bidVolume")


def chunk_names(first=FIRST_DAY, last=LAST_DAY):
    """Файлы набора идут подряд по 30 дней, последний обрезан."""
    d = FIRST_DAY
    while d <= LAST_DAY:
        e = min(d + dt.timedelta(days=29), LAST_DAY)
        if e >= first and d <= last:
            yield f"{d}_{e}"
        d += dt.timedelta(days=30)


def fetch(base_url, name, folder):
    target = folder / f"{name}.parquet"
    for attempt in range(6):
        try:
            req = urllib.request.Request(f"{base_url}/{name}.parquet",
                                         headers={"User-Agent": "xgboost-edge"})
            with urllib.request.urlopen(req, timeout=120) as r, target.open("wb") as f:
                length = r.headers.get("Content-Length")
                while block := r.read(1 << 20):
                    f.write(block)
            if length is not None and int(length) != target.stat().st_size:
                raise OSError("файл получен не полностью")
            return target
        except Exception as e:
            print(f"  {name}: {e} (попытка {attempt + 1})", flush=True)
            if attempt == 5:
                raise
            time.sleep(5 * 2 ** attempt)


def read_parquet(path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pq.read_table(path, columns=list(COLUMNS))
    if any(table[c].null_count for c in COLUMNS):
        raise ValueError(f"{path.name}: пустые значения")
    stamp = table["timestamp"]
    if pa.types.is_timestamp(stamp.type):
        stamp = stamp.cast(pa.timestamp("ms", stamp.type.tz))
    table = table.set_column(table.schema.get_field_index("timestamp"), "timestamp",
                             stamp.cast(pa.int64()))
    return {c: table[c].to_numpy() for c in COLUMNS}


def clean(data, last_ms, stats):
    """Отбрасывает неверные тики и тики из прошлого; возвращает записи TICK_DTYPE."""
    ts = np.asarray(data["timestamp"], dtype=np.int64)
    ask, bid, av, bv = (np.asarray(data[c], dtype=np.float64) for c in COLUMNS[1:])
    ok = (np.isfinite(ask) & np.isfinite(bid) & np.isfinite(av) & np.isfinite(bv)
          & (bid > 0) & (ask >= bid) & (av >= 0) & (bv >= 0))
    stats["invalid"] += int((~ok).sum())
    ts, ask, bid, av, bv = ts[ok], ask[ok], bid[ok], av[ok], bv[ok]
    if len(ts):
        floor = np.maximum.accumulate(np.concatenate(([last_ms], ts)))[:-1]
        ordered = ts >= floor
        stats["out_of_order"] += int((~ordered).sum())
        ts, ask, bid, av, bv = ts[ordered], ask[ordered], bid[ordered], av[ordered], bv[ordered]
    bi, ai = np.rint(bid * SCALE), np.rint(ask * SCALE)
    stats["off_grid"] += int(((np.abs(bid * SCALE - bi) > 1e-4) | (np.abs(ask * SCALE - ai) > 1e-4)).sum())
    out = np.empty(len(ts), TICK_DTYPE)
    out["time_ms"], out["bid"], out["ask"] = ts, bi, ai
    out["bid_volume"], out["ask_volume"] = bv, av
    # объём для баров берём из исходных чисел, до округления в float32
    real = np.floor(bv * 1_000_000 + 0.5).astype(np.int64)
    return out, real


def group(m, period, offset=0):
    """Объединяет строки (тики или младшие бары) в бары заданного периода."""
    key = (m["time"] - offset) // period * period + offset
    if not len(key):
        return {k: v[:0] for k, v in m.items()}
    start = np.flatnonzero(np.concatenate(([True], key[1:] != key[:-1])))
    end = np.concatenate((start[1:], [len(key)])) - 1
    return {
        "time": key[start], "open": m["open"][start],
        "high": np.maximum.reduceat(m["high"], start), "low": np.minimum.reduceat(m["low"], start),
        "close": m["close"][end],
        **{k: np.add.reduceat(m[k], start) for k in ("tick_volume", "spread_sum", "real_volume")},
    }


def ticks_to_m1(t, real):
    price = t["bid"] / SCALE
    return group({
        "time": t["time_ms"] // 1000, "open": price, "high": price, "low": price, "close": price,
        "tick_volume": np.ones(len(t), np.int64),
        "spread_sum": (t["ask"] - t["bid"]).astype(np.int64), "real_volume": real,
    }, 60)


def sunday_to_monday(m):
    sunday = (m["time"] // 86400 + 4) % 7 == 0
    return {**m, "time": np.where(sunday, (m["time"] // 86400 + 1) * 86400, m["time"])}


def check_range(ts, name):
    """Время в файле должно совпадать с датами в его имени (миллисекунды UTC)."""
    a, b = ((dt.date.fromisoformat(x) - dt.date(1970, 1, 1)).days * 86400_000 for x in name.split("_"))
    if len(ts) and not (a - 2 * 86400_000 <= ts.min() and ts.max() < b + 3 * 86400_000):
        raise SystemExit(f"{name}: время тиков не соответствует имени файла")


def save_xfbar(path, m, period):
    rec = np.empty(len(m["time"]), BAR_DTYPE)
    for k in ("time", "open", "high", "low", "close", "tick_volume", "real_volume"):
        rec[k] = m[k]
    rec["spread"] = np.floor(m["spread_sum"] / m["tick_volume"] + 0.5)
    sym = SYMBOL.encode()
    with open(path, "wb") as f:
        f.write(struct.pack("<8siiiidqqqi", b"XFBAR001", 1, 60, period, 5, POINT, len(rec),
                            int(rec["time"][0]), int(rec["time"][-1]), len(sym)) + sym)
        rec.tofile(f)


class TickYear:
    def __init__(self, folder, year):
        self.f = open(folder / f"{SYMBOL}_ticks_{year}.bin", "wb")
        self.f.write(bytes(64))
        self.count, self.first, self.last = 0, 0, 0

    def add(self, t):
        if not self.count:
            self.first = int(t["time_ms"][0])
        self.last = int(t["time_ms"][-1])
        self.count += len(t)
        t.tofile(self.f)

    def close(self):
        self.f.seek(0)
        self.f.write(struct.pack("<8sIIQqqd16x", b"EQTICK01", 1, 24, self.count,
                                 self.first, self.last, POINT))
        self.f.close()


def is_holiday(d):
    return (d.month, d.day) in ((1, 1), (12, 25))


def make_report(bars, years, stats, first, last, chunks):
    m1 = bars["M1"]
    days = m1["time"] // 86400
    per_day = collections.Counter(days.tolist())
    epoch = dt.date(1970, 1, 1)
    missing, thin = [], []
    d = first
    while d <= last:
        n = per_day.get((d - epoch).days, 0)
        if d.weekday() < 5 and not is_holiday(d):
            if n == 0:
                missing.append(str(d))
            # в полный день около 1440 минутных баров; пятница короче
            elif n < (1000 if d.weekday() < 4 else 900) and not (d.month == 12 and d.day in (24, 31)):
                thin.append(f"{d} ({n})")
        d += dt.timedelta(days=1)
    lines = [f"# База котировок {SYMBOL}", "",
             f"Период: {first} .. {last}. Время UTC, цены баров Bid.",
             "Неделя с воскресенья; в D1 воскресный вечер входит в понедельник.",
             f"Исходных файлов: {chunks}.", "",
             "## Тики по годам", "", "| Год | Тиков | Первый | Последний |", "|---|---|---|---|"]
    stamp = lambda ms: f"{dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc):%Y-%m-%d %H:%M}"
    for y, (n, a, b) in sorted(years.items()):
        lines.append(f"| {y} | {n} | {stamp(a)} | {stamp(b)} |")
    lines += ["", "## Бары", "", "| Таймфрейм | Баров |", "|---|---|"]
    lines += [f"| {tf} | {len(bars[tf]['time'])} |" for tf in TIMEFRAMES]
    lines += ["", "## Проверка", "",
              f"- Неверных тиков отброшено: {stats['invalid']}",
              f"- Тиков не по порядку отброшено: {stats['out_of_order']}",
              f"- Цен не кратных 0.00001: {stats['off_grid']}",
              f"- Будних дней без данных (кроме 1.01 и 25.12): {len(missing)}",
              f"- Будних дней с неполными данными: {len(thin)}", ""]
    if missing:
        lines += ["### Дни без данных", "", ", ".join(missing), ""]
    if thin:
        lines += ["### Неполные дни (число баров M1)", "", ", ".join(thin), ""]
    return "\n".join(lines)


def build(base_url, out, report, first=FIRST_DAY, last=LAST_DAY, reader=read_parquet):
    folder = Path(out) / SYMBOL
    (folder / "ticks").mkdir(parents=True, exist_ok=True)
    tmp = Path(out) / "_download"
    tmp.mkdir(exist_ok=True)
    names = list(chunk_names(first, last))
    stats = collections.Counter()
    years, writer, writer_year, parts, last_ms = {}, None, None, [], 0

    def close_year():
        writer.close()
        years[writer_year] = (writer.count, writer.first, writer.last)

    with ThreadPoolExecutor(max_workers=4) as pool:
        queue = collections.deque()
        rest = iter(names)
        done = 0
        while True:
            while len(queue) < 4 and (n := next(rest, None)):
                queue.append(pool.submit(fetch, base_url, n, tmp))
            if not queue:
                break
            path = queue.popleft().result()
            data = reader(path)
            check_range(np.asarray(data["timestamp"], dtype=np.int64), path.stem)
            ticks, real = clean(data, last_ms, stats)
            path.unlink()
            done += 1
            print(f"{done}/{len(names)} {path.stem}: {len(ticks)} тиков", flush=True)
            if not len(ticks):
                continue
            last_ms = int(ticks["time_ms"][-1])
            year_of = ticks["time_ms"].astype("datetime64[ms]").astype("datetime64[Y]").astype(int) + 1970
            for y in np.unique(year_of):
                if y != writer_year:
                    if writer:
                        close_year()
                    writer, writer_year = TickYear(folder / "ticks", int(y)), int(y)
                writer.add(ticks[year_of == y])
            parts.append(ticks_to_m1(ticks, real))
    if not writer:
        raise SystemExit("нет ни одного тика")
    close_year()
    m1 = group({k: np.concatenate([p[k] for p in parts]) for k in parts[0]}, 60)
    bars = {}
    for tf, (period, offset) in TIMEFRAMES.items():
        bars[tf] = group(sunday_to_monday(m1) if tf == "D1" else m1, period, offset)
        save_xfbar(folder / f"{SYMBOL}_{tf}.bin", bars[tf], period)
    tmp.rmdir()
    text = make_report(bars, years, stats, first, last, len(names))
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/quotes")
    ap.add_argument("--report", default="reports/quotes_EURUSD.md")
    ap.add_argument("--base-url", default=BASE_URL)
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    build(a.base_url, a.out, a.report)
