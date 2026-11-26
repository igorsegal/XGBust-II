# -*- coding: utf-8 -*-
"""Локальная копия базы EURUSD в D:\\EURUSD (тот же расчёт, что на GitHub).

Скачанные раньше файлы parquet берутся с диска (оригиналы не изменяются и не удаляются),
недостающие скачиваются с Hugging Face. В конце результат сверяется с отчётом GitHub.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import build_quotes as q

OUT = Path("D:/")                                  # база будет в D:\EURUSD
LOCAL = Path("D:/Tickstory/DATA/HF_EURUSD")        # уже скачанные parquet
NEED_BYTES = 9 * 1024 ** 3
# числа из отчёта GitHub reports/quotes_EURUSD.md от 25.11.2026
TICKS = {2016: 44832601, 2017: 21704582, 2018: 26048831, 2019: 29190340, 2020: 32763984,
         2021: 16797709, 2022: 36950672, 2023: 27553506, 2024: 20690554, 2025: 23463391,
         2026: 7457688}
BARS = {"M1": 3849994, "M5": 772727, "M15": 257627, "M30": 128824,
        "H1": 64418, "H4": 16648, "D1": 2694, "W1": 539}

download = q.fetch


def fetch(base_url, name, folder):
    source = LOCAL / f"mito_{name}.parquet"
    if source.is_file():
        target = folder / f"{name}.parquet"
        shutil.copyfile(source, target)            # сборка удаляет только эту копию
        return target
    return download(base_url, name, folder)


def verify(folder):
    wrong = []
    for year, n in TICKS.items():
        p = folder / "ticks" / f"EURUSD_ticks_{year}.bin"
        got = (p.stat().st_size - 64) // 24 if p.is_file() else 0
        if got != n:
            wrong.append(f"тики {year}: {got} вместо {n}")
    for tf, n in BARS.items():
        p = folder / f"EURUSD_{tf}.bin"
        got = (p.stat().st_size - 66) // 60 if p.is_file() else 0
        if got != n:
            wrong.append(f"бары {tf}: {got} вместо {n}")
    return wrong


def main():
    folder = OUT / "EURUSD"
    present = sum(p.stat().st_size for p in folder.rglob("*.bin")) if folder.is_dir() else 0
    free = shutil.disk_usage(OUT).free + present
    if free < NEED_BYTES:
        print(f"STOP: NOT ENOUGH SPACE. Free {free / 1024 ** 3:.1f} GB, need 9 GB.")
        return 1
    q.fetch = fetch
    q.build(q.BASE_URL, OUT, folder / "REPORT.txt")
    wrong = verify(folder)
    print()
    if wrong:
        print("\n".join(wrong))
        print("CHECK FAILED")
        return 1
    print("LOCAL BASE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
