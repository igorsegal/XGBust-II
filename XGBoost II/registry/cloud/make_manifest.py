# -*- coding: utf-8 -*-
"""Паспорт локальной базы: число баров и контрольные суммы файлов (сами котировки в паспорт не входят).

Использование: python make_manifest.py <папка BAZA> <выходной bars_manifest.json>
"""
import datetime as dt
import hashlib
import json
import struct
import sys
from pathlib import Path

SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD")
TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4", "D1", "W1")


def describe(path):
    """Паспорт одного файла баров XFBAR001."""
    data = Path(path).read_bytes()
    magic, _, size, _, _, _, count, first, last, name_len = struct.unpack_from("<8siiiidqqqi", data)
    offset = 60 + name_len
    if magic != b"XFBAR001" or size != 60 or len(data) != offset + 60 * count:
        raise SystemExit(f"STOP: испорченный файл {path}")
    years, start, current = {}, offset, None
    for pos in range(offset, len(data) + 1, 60):
        year = None
        if pos < len(data):
            year = dt.datetime.fromtimestamp(struct.unpack_from("<q", data, pos)[0], dt.timezone.utc).year
        if year != current:
            if current is not None:
                years[str(current)] = [(pos - start) // 60, hashlib.sha256(data[start:pos]).hexdigest()]
            start, current = pos, year
    stamp = lambda t: f"{dt.datetime.fromtimestamp(t, dt.timezone.utc):%Y-%m-%d %H:%M}"
    return {"bars": count, "first": stamp(first), "last": stamp(last),
            "sha256": hashlib.sha256(data).hexdigest(), "years": years}


def main(folder, out):
    files = {f"{s}_{tf}": describe(Path(folder) / s / f"{s}_{tf}.bin") for s in SYMBOLS for tf in TIMEFRAMES}
    Path(out).write_text(json.dumps({"source": "локальная база BAZA", "files": files}, indent=1) + "\n",
                         encoding="utf-8")
    print(f"файлов в паспорте: {len(files)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
