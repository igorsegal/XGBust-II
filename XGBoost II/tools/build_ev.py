# -*- coding: utf-8 -*-
"""USDJPY и AUDUSD для D:\\BAZA из набора expected-value/dukascopy-ticks (Hugging Face, помесячные тики).

Перед сборкой один и тот же отрезок сравнивается с набором mito0o852, из которого собраны остальные
инструменты: время и цены обязаны совпасть. Прерванную загрузку можно запустить снова.
"""
import datetime as dt
import json
import re
import shutil
import sys
import urllib.request

import numpy as np

import build_baza as b

q = b.q
EV = "expected-value/dukascopy-ticks"
# инструмент -> (папка, знаков, нужно ГБ, с какого дня, (файл mito для сверки, месяц здесь))
SYMBOLS = {
    "USDJPY": ("usd_jpy", 3, 12, dt.date(2020, 1, 1), ("2022-09-26_2022-10-25", "2022_10")),
    "AUDUSD": ("aud_usd", 5, 10, dt.date(2020, 4, 1), ("2023-09-21_2023-10-20", "2023_10")),
}
DAY = dt.timedelta(days=1)


def day_ms(d):
    return (d - dt.date(1970, 1, 1)).days * 86400_000


def list_ev(pair):
    """Месяцы и размеры файлов инструмента."""
    url = f"https://huggingface.co/api/datasets/{EV}/tree/main/{pair}"
    files = {}
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "xgboost-edge"})
        with urllib.request.urlopen(req, timeout=120) as r:
            for f in json.load(r):
                name = f["path"].rsplit("/", 1)[1]
                if re.fullmatch(r"\d{4}_\d\d\.parquet", name):
                    files[name[:-8]] = f.get("lfs", f)["size"]
            m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
        url = m.group(1) if m else None
    return files


def read_ev(path):
    """Файл месяца в тех же колонках, что и набор mito0o852."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    names = ["timestamp", "ask", "bid", "ask_volume", "bid_volume"]
    table = pq.read_table(path, columns=names)
    if any(table[c].null_count for c in names):
        raise ValueError(f"{path.name}: пустые значения")
    stamp = table["timestamp"]
    per_ms = {"ms": 1, "us": 1000, "ns": 1000_000}[stamp.type.unit]
    ts = (stamp.cast(pa.int64()).to_numpy() + per_ms // 2) // per_ms
    return {"timestamp": ts, **{new: table[old].to_numpy() for new, old in zip(q.COLUMNS[1:], names[1:])}}


def months(first, last):
    """[(месяц, первый день, последний день)] от first до last."""
    d = first
    while d <= last:
        nxt = (d.replace(day=1) + 32 * DAY).replace(day=1)
        yield f"{d:%Y_%m}", d, min(nxt - DAY, last)
        d = nxt


def compare(symbol, ours, other, scale):
    """Общий отрезок двух наборов: время и цены совпадают. Возвращает множитель объёма."""
    ta, tb = (np.asarray(x["timestamp"], dtype=np.int64) for x in (ours, other))
    if not len(ta) or not len(tb):
        raise SystemExit(f"STOP: {symbol}: для сверки нет тиков")
    lo, hi = max(ta.min(), tb.min()), min(ta.max(), tb.max())
    ua, ia = np.unique(ta, return_index=True)
    ub, ib = np.unique(tb, return_index=True)
    na, nb = (int(((u >= lo) & (u <= hi)).sum()) for u in (ua, ub))
    _, x, y = np.intersect1d(ua, ub, assume_unique=True, return_indices=True)
    x, y = ia[x], ib[y]
    if len(x) < 10000:
        raise SystemExit(f"STOP: {symbol}: наборы не совпали по времени: общих тиков {len(x)} из {na} и {nb}")
    timed = len(x) / max(na, nb)
    same = np.ones(len(x), bool)
    for c in ("bidPrice", "askPrice"):
        same &= np.rint(np.asarray(ours[c])[x] * scale) == np.rint(np.asarray(other[c])[y] * scale)
    priced = same.mean()
    print(f"{symbol}: сверка наборов: тиков {na} и {nb}, совпало по времени {timed:.2%}, по ценам {priced:.3%}",
          flush=True)
    if timed < 0.99 or priced < 0.999:
        raise SystemExit(f"STOP: {symbol}: наборы расходятся, базу не строю")
    a = np.asarray(ours["bidVolume"], float)[x]
    z = np.asarray(other["bidVolume"], float)[y]
    use = (a > 0) & (z > 0)
    factor = float(f"{np.median(z[use] / a[use]):.4g}")
    fit = np.isclose(a[use] * factor, z[use], rtol=1e-3, atol=1e-9).mean()
    if fit < 0.99:
        raise SystemExit(f"STOP: {symbol}: объёмы наборов не сопоставляются ({fit:.2%})")
    print(f"{symbol}: объёмы совпали, множитель {factor:g}", flush=True)
    return factor, f"по времени {timed:.2%}, по ценам {priced:.3%}"


def build_symbol(symbol, pair, digits, start, check):
    q.FIRST_DAY = start
    remote = list_ev(pair)
    plan = {f"{a}_{z}": ym for ym, a, z in months(start, q.LAST_DAY)}
    lost = [ym for ym in plan.values() if ym not in remote]
    if lost:
        raise SystemExit(f"STOP: {symbol}: в наборе нет месяцев: {', '.join(lost[:6])}")
    files = {name: remote[ym] for name, ym in plan.items()}
    base = f"https://huggingface.co/datasets/{EV}/resolve/main/{pair}"
    check_dir = b.OUT / "_cache" / symbol / "check"
    check_dir.mkdir(parents=True, exist_ok=True)
    mito, month = check
    print(f"{symbol}: скачиваю два файла для сверки", flush=True)
    theirs = b.download(f"https://huggingface.co/datasets/{b.REPO}/resolve/main/data/{symbol}", mito, check_dir)
    mine = b.download(base, month, check_dir)
    factor, result = compare(symbol, read_ev(mine), q.read_parquet(theirs), 10 ** digits)

    def fetcher(base_url, name, folder):
        return b.download(base, plan[name], folder)

    def reader(path):
        data = read_ev(path)
        a, z = (dt.date.fromisoformat(x) for x in path.stem.split("_"))
        ts = data["timestamp"]
        keep = (ts >= day_ms(a)) & (ts < day_ms(z + DAY))
        if not keep.all() and z != q.LAST_DAY:
            raise SystemExit(f"STOP: {symbol} {path.stem}: в файле месяца есть тики другого месяца")
        data = {k: np.asarray(v)[keep] for k, v in data.items()}
        data["bidVolume"] = data["bidVolume"] * factor
        data["askVolume"] = data["askVolume"] * factor
        return data

    (b.OUT / symbol).mkdir(parents=True, exist_ok=True)
    (b.OUT / symbol / "REPORT.txt").unlink(missing_ok=True)
    price, _, last = b.build_symbol(symbol, digits, files, reader, fetcher)
    with open(b.OUT / symbol / "REPORT.txt", "a", encoding="utf-8") as f:
        f.write(f"- Тики взяты из набора {EV}; сверка с {b.REPO} за {mito}: {result}\n")
    return price, last


def main():
    saved, done = q.FIRST_DAY, []
    if (b.OUT / "XAUUSD" / "REPORT.txt").is_file():       # остаток прерванной попытки через Dukascopy
        shutil.rmtree(b.OUT / "_cache" / "XAUUSD", ignore_errors=True)
    for symbol, (pair, digits, need, start, check) in SYMBOLS.items():
        report = b.OUT / symbol / "REPORT.txt"
        if report.is_file() and EV in report.read_text(encoding="utf-8"):
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
        price, last = build_symbol(symbol, pair, digits, start, check)
        done.append(f"{symbol}: OK, {start}..{last}, цена {price[0]:.{digits}f}..{price[1]:.{digits}f}")
    q.FIRST_DAY = saved
    print("\n" + "\n".join(done))
    print("BAZA EV OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
