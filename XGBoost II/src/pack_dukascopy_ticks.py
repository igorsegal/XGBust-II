import os
import lzma
import struct
import calendar
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
# Структура записи Dukascopy .bi5: >IIIff (20 байт, big-endian)
BI5_STRUCT = struct.Struct(">IIIff")
# Выходная компактная запись V3TICK1: <IfH (10 байт: uint32 unix_sec, float bid, uint16 spread_points)
TICK_OUT_STRUCT = struct.Struct("<IfH")
def process_day_folder(args):
    day_dir_str, year, month_0based, day, point_mult, inv_point = args
    day_dir = Path(day_dir_str)
    out_buf = bytearray()
    last_bid_int = -1
    last_ask_int = -1
    kept = 0
    for hour in range(24):
        bi5_file = day_dir / f"{hour:02d}h_ticks.bi5"
        if not bi5_file.exists() or bi5_file.stat().st_size == 0:
            continue
        try:
            raw = lzma.decompress(bi5_file.read_bytes())
        except Exception:
            continue
        base_ts = calendar.timegm((year, month_0based + 1, day, hour, 0, 0))
        n_ticks = len(raw) // 20
        for i in range(n_ticks):
            ms, ask_int, bid_int, _, _ = BI5_STRUCT.unpack_from(raw, i * 20)
            # Фильтр дубликатов: пропускаем тик, если ни Bid, ни Ask не изменились
            if bid_int == last_bid_int and ask_int == last_ask_int:
                continue
            last_bid_int = bid_int
            last_ask_int = ask_int
            ts_sec = base_ts + (ms // 1000)
            bid_f = bid_int * point_mult
            spread_pts = max(0, min(65535, ask_int - bid_int))
            out_buf += TICK_OUT_STRUCT.pack(ts_sec, bid_f, spread_pts)
            kept += 1
    day_start_ts = calendar.timegm((year, month_0based + 1, day, 0, 0, 0))
    return day_start_ts, kept, bytes(out_buf)
def main():
    root = Path(r"D:\Tickstory\DATA\EURUSD")
    out_path = Path("data/cache/EURUSD_ticks.bin")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tasks = []
    for y_dir in sorted(root.iterdir()):
        if not y_dir.is_dir() or not y_dir.name.isdigit():
            continue
        year = int(y_dir.name)
        for m_dir in sorted(y_dir.iterdir()):
            if not m_dir.is_dir() or not m_dir.name.isdigit():
                continue
            month_0 = int(m_dir.name)
            for d_dir in sorted(m_dir.iterdir()):
                if not d_dir.is_dir() or not d_dir.name.isdigit():
                    continue
                day = int(d_dir.name)
                tasks.append((str(d_dir), year, month_0, day, 1e-5, 100000))
    print(f"Найдено торговых дней для упаковки: {len(tasks)}. Распаковка LZMA в многопотоке...")
    day_results = []
    with ProcessPoolExecutor() as ex:
        for res in ex.map(process_day_folder, tasks, chunksize=16):
            if res[1] > 0:
                day_results.append(res)
    day_results.sort(key=lambda x: x[0])
    # Заголовок V3TICK1:
    # magic[8] = "V3TICK01", float point = 1e-5, uint32 num_days, uint64 total_ticks
    # Далее таблица индекса дней: (uint32 day_ts, uint64 start_tick_idx, uint32 num_ticks) * num_days
    # Далее плотный массив тиков по 10 байт: (uint32 ts_sec, float bid, uint16 spread_pts)
    total_ticks = sum(r[1] for r in day_results)
    num_days = len(day_results)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<8sfIQ", b"V3TICK01", 1e-5, num_days, total_ticks))
        cursor = 0
        for day_ts, count, _ in day_results:
            f.write(struct.pack("<IQI", day_ts, cursor, count))
            cursor += count
        for _, _, blob in day_results:
            f.write(blob)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"✅ Готово! Упаковано {total_ticks:,} уникальных тиков за {num_days} дней в {out_path} ({size_mb:.1f} МБ)")
if __name__ == "__main__":
    main()
