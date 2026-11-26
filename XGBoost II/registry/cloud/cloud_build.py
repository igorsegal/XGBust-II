# -*- coding: utf-8 -*-
"""Сборка баров одного инструмента на сервере GitHub теми же программами, что и локальная база.

Отличия от локальной сборки: тики на диск не пишутся (тестеру нужны только бары), берутся только
файлы источника с 2020 года, и всё после последней даты локальной базы отрезается.
Использование: python cloud_build.py <инструмент> <папка базы>
"""
import datetime as dt
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import build_baza as b
import build_ev as k

q = b.q
START = dt.date(2020, 1, 1)
ORIGIN = dt.date(2016, 1, 1)      # локальная база GBPUSD и XAUUSD выбирала файлы источника начиная с этого дня
MITO = {"EURUSD": 5, "GBPUSD": 5, "XAUUSD": 3}
END = {"XAUUSD": dt.date(2026, 4, 2)}          # последний день локальной базы; для остальных q.LAST_DAY
DAY = dt.timedelta(days=1)


class CountOnly:
    """Вместо записи файлов тиков только считает их (для отчёта)."""

    def __init__(self, folder, year):
        self.count, self.first, self.last = 0, 0, 0

    def add(self, t):
        if not self.count:
            self.first = int(t["time_ms"][0])
        self.last = int(t["time_ms"][-1])
        self.count += len(t)

    def close(self):
        pass


def cut_after(reader, end):
    """Читатель, отбрасывающий тики позже дня end."""
    limit = k.day_ms(end + DAY)

    def read(path):
        data = reader(path)
        keep = np.asarray(data["timestamp"], dtype=np.int64) < limit
        return {name: np.asarray(v)[keep] for name, v in data.items()}

    return read


def trim(folder, symbol):
    """Оставляет бары с 2020 года, как в локальной базе."""
    start = (START - dt.date(1970, 1, 1)).days * 86400
    for path in sorted(folder.glob(f"{symbol}_*.bin")):
        data = path.read_bytes()
        head = list(struct.unpack_from("<8siiiidqqqi", data))
        offset = 60 + head[-1]
        rec = np.frombuffer(data, q.BAR_DTYPE, offset=offset)
        keep = rec[rec["time"] >= start]
        if not len(keep):
            raise SystemExit(f"STOP: {path.name}: нет баров с {START}")
        head[6], head[7], head[8] = len(keep), int(keep["time"][0]), int(keep["time"][-1])
        path.write_bytes(struct.pack("<8siiiidqqqi", *head) + data[60:offset] + keep.tobytes())


def pick(files):
    """Те же файлы источника, что при выборе с 2016 года, но только нужные для 2020 года и позже."""
    saved, q.FIRST_DAY = q.FIRST_DAY, ORIGIN
    chosen, _ = b.cover(files)
    q.FIRST_DAY = saved
    need = [(n, d) for n, d in chosen if dt.date.fromisoformat(n.split("_")[1]) >= START]
    if not need:
        raise SystemExit("STOP: в источнике нет файлов с 2020 года")
    return {n: files[n] for n, _ in need}, need[0][1]


def build(symbol, out):
    b.OUT = Path(out)
    b.OUT.mkdir(parents=True, exist_ok=True)
    q.TickYear = CountOnly
    last_day = q.LAST_DAY
    end = END.get(symbol, last_day)
    if symbol in MITO:
        files, first = pick(b.list_files(symbol))
        files = {n: s for n, s in files.items() if dt.date.fromisoformat(n.split("_")[0]) <= end}
        q.FIRST_DAY = first
        b.build_symbol(symbol, MITO[symbol], files, cut_after(q.read_parquet, end))
    else:
        pair, digits, _, start, check = k.SYMBOLS[symbol]
        k.build_symbol(symbol, pair, digits, start, check)
    trim(b.OUT / symbol, symbol)
    print(f"CLOUD BUILD OK {symbol}")


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    build(sys.argv[1], sys.argv[2])
