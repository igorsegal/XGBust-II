# -*- coding: utf-8 -*-
"""Единая база D:\\BAZA с 1 января 2020: EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD.

Данные до 2020 года не удаляются, а переносятся в D:\\BAZA\\_old_do_2020.
"""
import datetime as dt
import os
import struct
import sys
from pathlib import Path

import numpy as np

import build_ev as k

b, q = k.b, k.q
START = dt.date(2020, 1, 1)
START_S = (START - dt.date(1970, 1, 1)).days * 86400
OLD_EURUSD = Path("D:/EURUSD")
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD")
NOTE = "- В базе оставлены данные с 2020-01-01 (таблицы выше посчитаны до обрезки)\n"
q.FIRST_DAY = START


def trim(symbol):
    """Оставляет бары и тики с 2020 года; прежние файлы переносит в _old_do_2020."""
    folder, old = b.OUT / symbol, b.OUT / "_old_do_2020" / symbol
    if not folder.is_dir():
        return False
    changed = False
    for path in sorted(folder.glob(f"{symbol}_*.bin")):
        data = path.read_bytes()
        head = list(struct.unpack_from("<8siiiidqqqi", data))
        offset = 60 + head[-1]
        rec = np.frombuffer(data, q.BAR_DTYPE, offset=offset)
        keep = rec[rec["time"] >= START_S]
        if len(keep) == len(rec) or not len(keep):
            continue
        head[6], head[7], head[8] = len(keep), int(keep["time"][0]), int(keep["time"][-1])
        part = path.with_suffix(".part")
        part.write_bytes(struct.pack("<8siiiidqqqi", *head) + data[60:offset] + keep.tobytes())
        old.mkdir(parents=True, exist_ok=True)
        if not (old / path.name).exists():
            os.replace(path, old / path.name)
        os.replace(part, path)
        changed = True
    for path in sorted((folder / "ticks").glob(f"{symbol}_ticks_*.bin")):
        if int(path.stem.rsplit("_", 1)[1]) < START.year:
            (old / "ticks").mkdir(parents=True, exist_ok=True)
            os.replace(path, old / "ticks" / path.name)
            changed = True
    report = folder / "REPORT.txt"
    if changed and report.is_file():
        text = report.read_text(encoding="utf-8")
        if NOTE not in text and f"Период: {START}" not in text:
            report.write_text(text + NOTE, encoding="utf-8")
    return changed


def move_eurusd():
    """Переносит D:\\EURUSD в общую базу (по файлам, чтобы не мешали открытые окна)."""
    if not OLD_EURUSD.is_dir() or not any(OLD_EURUSD.iterdir()):
        return True
    target = b.OUT / "EURUSD"
    target.mkdir(exist_ok=True)
    for item in list(OLD_EURUSD.iterdir()):
        try:
            if (target / item.name).exists():
                print(f"STOP: уже есть {target / item.name}, а в {OLD_EURUSD} лежит второй. Ничего не заменяю.")
                return False
            os.rename(item, target / item.name)
        except OSError as e:
            print(f"STOP: не удалось перенести {item}: {e}. Закройте окна с этой папкой и запустите снова.")
            return False
    try:
        OLD_EURUSD.rmdir()
    except OSError:
        pass                                              # пустую папку можно удалить позже
    print(f"{OLD_EURUSD} перенесена в {target}")
    return True


def main():
    b.OUT.mkdir(parents=True, exist_ok=True)
    if not move_eurusd():
        return 1
    for symbol in SYMBOLS:
        if trim(symbol):
            print(f"{symbol}: оставлены данные с {START}")
    code = k.main()
    if code:
        return code
    for symbol in SYMBOLS:
        trim(symbol)
        if not (b.OUT / symbol / f"{symbol}_M1.bin").is_file():
            print(f"STOP: нет базы {symbol}")
            return 1
    print("QUOTES 2020 OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
