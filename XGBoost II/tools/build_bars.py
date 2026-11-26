# build_bars.py version 1
# Parquet ticks (Tickstory export) -> XFBAR001 bar files M1, M5, M15, H1, H4, D1.
# Same rules as the C++ xfbar_exporter: bid prices, tick_volume = tick count,
# spread = mean of per-tick (ask-bid) in points, real_volume = sum(bidVolume*1e6).
import sys, os, glob, struct, time
import numpy as np

POINT = 0.00001
INV_POINT = 1.0 / POINT
DIGITS = 5
TFS = [("M1", 60), ("M5", 300), ("M15", 900), ("H1", 3600), ("H4", 14400), ("D1", 86400)]
REC = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
                ("close", "<f8"), ("tick_volume", "<i8"), ("spread", "<i4"),
                ("real_volume", "<i8")], align=False)
assert REC.itemsize == 60


def rnd(x):
    # llround for non-negative numbers (half away from zero)
    return np.floor(x + 0.5).astype(np.int64)


class State:
    def __init__(self):
        self.cummax = np.iinfo(np.int64).min
        self.parts = []          # list of tuples (key,o,h,l,c,n,spsum,rv)
        self.rows = 0
        self.invalid = 0
        self.out_of_order = 0
        self.valid = 0


def group(key, o, h, l, c, n, sp, rv):
    """key must be non-decreasing. Returns merged arrays, one row per distinct key."""
    if len(key) == 0:
        return key, o, h, l, c, n, sp, rv
    starts = np.flatnonzero(np.concatenate(([True], key[1:] != key[:-1])))
    ends = np.concatenate((starts[1:], [len(key)]))
    return (key[starts], o[starts], np.maximum.reduceat(h, starts),
            np.minimum.reduceat(l, starts), c[ends - 1],
            np.add.reduceat(n, starts), np.add.reduceat(sp, starts),
            np.add.reduceat(rv, starts))


def add_batch(st, ts, ask, bid, avol, bvol):
    st.rows += len(ts)
    valid = (np.isfinite(ask) & np.isfinite(bid) & np.isfinite(avol) & np.isfinite(bvol)
             & (ask > 0.0) & (bid > 0.0) & (ask >= bid) & (avol >= 0.0) & (bvol >= 0.0))
    st.invalid += int((~valid).sum())
    ts, ask, bid, bvol = ts[valid], ask[valid], bid[valid], bvol[valid]
    if len(ts) == 0:
        return
    cm = np.maximum.accumulate(np.concatenate(([st.cummax], ts)))
    keep = ts >= cm[:-1]
    st.out_of_order += int((~keep).sum())
    st.cummax = int(cm[-1])
    ts, ask, bid, bvol = ts[keep], ask[keep], bid[keep], bvol[keep]
    if len(ts) == 0:
        return
    st.valid += len(ts)
    key = (ts // 1000) // 60 * 60
    spp = rnd((ask - bid) * INV_POINT)
    rv = rnd(bvol * 1_000_000.0)
    one = np.ones(len(ts), dtype=np.int64)
    st.parts.append(group(key, bid, bid, bid, bid, one, spp, rv))


def finish_m1(st):
    cols = [np.concatenate([p[i] for p in st.parts]) for i in range(8)]
    order = np.argsort(cols[0], kind="stable")
    cols = [c[order] for c in cols]
    return group(*cols)


def to_tf(m1, period):
    key, o, h, l, c, n, sp, rv = m1
    return group(key // period * period, o, h, l, c, n, sp, rv)


def to_records(g):
    key, o, h, l, c, n, sp, rv = g
    r = np.zeros(len(key), dtype=REC)
    r["time"], r["open"], r["high"], r["low"], r["close"] = key, o, h, l, c
    r["tick_volume"] = n
    r["spread"] = rnd(sp / n).astype(np.int32)
    r["real_volume"] = rv
    return r


def save(path, rec, symbol, period):
    sym = symbol.encode("utf-8")
    hdr = struct.pack("<8siiiidqqqi", b"XFBAR001", 1, 60, period, DIGITS, POINT,
                      len(rec), int(rec["time"][0]) if len(rec) else 0,
                      int(rec["time"][-1]) if len(rec) else 0, len(sym))
    assert len(hdr) == 60
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(sym)
        f.write(rec.tobytes())


def load_bin(path):
    b = open(path, "rb").read()
    sl = struct.unpack_from("<i", b, 56)[0]
    return np.frombuffer(b, dtype=REC, offset=60 + sl)


def selftest():
    rng = np.random.default_rng(7)
    n = 60000
    ts = np.cumsum(rng.integers(0, 4000, n)) + 1640822400000
    bid = 1.1 + np.cumsum(rng.normal(0, 0.00002, n))
    bid = np.round(bid, 5)
    ask = np.round(bid + rng.integers(1, 6, n) * POINT, 5)
    avol = rng.random(n) * 3
    bvol = rng.random(n) * 3
    # reference: direct port of the C++ loop
    def ref(period):
        bars = []
        cur = None
        for i in range(n):
            bs = (ts[i] // 1000) // period * period
            sp = int(np.floor((ask[i] - bid[i]) * INV_POINT + 0.5))
            rv = int(np.floor(bvol[i] * 1e6 + 0.5))
            if cur is None or bs != cur[0]:
                if cur is not None:
                    bars.append(cur)
                cur = [bs, bid[i], bid[i], bid[i], bid[i], 1, sp, rv]
            else:
                cur[2] = max(cur[2], bid[i]); cur[3] = min(cur[3], bid[i])
                cur[4] = bid[i]; cur[5] += 1; cur[6] += sp; cur[7] += rv
        bars.append(cur)
        return bars
    st = State()
    for a in range(0, n, 7919):            # odd batch size: batches split minutes
        b = slice(a, a + 7919)
        add_batch(st, ts[b], ask[b], bid[b], avol[b], bvol[b])
    m1 = finish_m1(st)
    ok = True
    for name, period in TFS:
        rec = to_records(to_tf(m1, period))
        r = ref(period)
        good = len(r) == len(rec)
        if good:
            for i, x in enumerate(r):
                y = rec[i]
                avg = int(np.floor(x[6] / x[5] + 0.5))
                if not (x[0] == y["time"] and x[1] == y["open"] and x[2] == y["high"] and x[3] == y["low"]
                        and x[4] == y["close"] and x[5] == y["tick_volume"] and avg == y["spread"]
                        and x[7] == y["real_volume"]):
                    good = False
                    break
        print("selftest", name, "bars", len(rec), "OK" if good else "MISMATCH")
        ok = ok and good
    # out-of-order and invalid ticks are dropped
    st2 = State()
    add_batch(st2, np.array([1000, 3000, 2000, 4000]), np.array([1.2, 1.2, 1.2, 1.1]),
              np.array([1.1999, 1.1999, 1.1999, 1.12]), np.array([1.0] * 4), np.array([1.0] * 4))
    print("selftest drop: valid", st2.valid, "invalid", st2.invalid, "out_of_order", st2.out_of_order,
          "OK" if (st2.valid == 2 and st2.invalid == 1 and st2.out_of_order == 1) else "MISMATCH")
    ok = ok and st2.valid == 2 and st2.invalid == 1 and st2.out_of_order == 1
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(0 if selftest() else 1)
    if len(sys.argv) < 4:
        print("usage: build_bars.py <parquet_dir> <SYMBOL> <out_dir>")
        sys.exit(2)
    import pyarrow.parquet as pq
    src, symbol, out = sys.argv[1], sys.argv[2], sys.argv[3]
    files = sorted(glob.glob(os.path.join(src, "*.parquet")))
    if not files:
        print("NO PARQUET FILES in", src); sys.exit(2)
    os.makedirs(out, exist_ok=True)
    st = State()
    t0 = time.time()
    cols = ["timestamp", "askPrice", "bidPrice", "askVolume", "bidVolume"]
    for f in files:
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=2_000_000, columns=cols):
            a = [batch.column(i).to_numpy(zero_copy_only=False) for i in range(5)]
            add_batch(st, a[0].astype(np.int64), a[1].astype(np.float64), a[2].astype(np.float64),
                      a[3].astype(np.float64), a[4].astype(np.float64))
        print("%s  ticks so far %d  (%.0f s)" % (os.path.basename(f), st.valid, time.time() - t0), flush=True)
    m1 = finish_m1(st)
    print("rows read %d, valid %d, invalid %d, out of order %d" % (st.rows, st.valid, st.invalid, st.out_of_order))
    for name, period in TFS:
        rec = to_records(to_tf(m1, period))
        p = os.path.join(out, "%s_%s.bin" % (symbol, name))
        save(p, rec, symbol, period)
        chk = load_bin(p)
        assert len(chk) == len(rec) and bool((chk == rec).all())
        t = rec["time"]
        print("%s: %d bars, %s .. %s  -> %s" % (name, len(rec),
              time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(t[0]))),
              time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(t[-1]))), p))
    # compare with the existing one-month files
    for name, period in (("M1", 60), ("M5", 300)):
        old = os.path.join(src, "%s_%s.bin" % (symbol, name))
        if os.path.exists(old):
            o = load_bin(old)
            n = to_records(to_tf(m1, period))
            sel = n[(n["time"] >= o["time"][0]) & (n["time"] <= o["time"][-1])]
            same = len(sel) == len(o) and bool((sel == o).all())
            diff = int((sel != o).sum()) if len(sel) == len(o) else -1
            print("COMPARE %s with old file: %s (bars new %d, old %d, different %d)" % (
                name, "IDENTICAL" if same else "DIFFERENT", len(sel), len(o), diff))
    print("DONE")


if __name__ == "__main__":
    main()
