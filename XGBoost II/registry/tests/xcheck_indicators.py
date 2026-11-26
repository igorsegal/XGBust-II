#!/usr/bin/env python3
"""xcheck_indicators.py - независимая проверка индикаторов тестера.
Считает индикаторы заново на Python по формулам из indicators_catalog.json (другим способом: прямые циклы по окну),
запускает `tester --dump` и сравнивает значения по каждому бару. Допуск 1e-7 (абсолютный и относительный).
Использование: python xcheck_indicators.py <tester> <файл баров XFBAR001> [число баров с конца]"""
import struct, subprocess, sys, math

def load(path):
    f = open(path, "rb"); d = f.read(); f.close()
    assert d[:8] == b"XFBAR001"
    n = struct.unpack_from("<q", d, 8 + 4 * 4 + 8)[0]
    sl = struct.unpack_from("<i", d, 8 + 4 * 4 + 8 + 8 * 3)[0]
    off = 8 + 16 + 8 + 24 + 4 + sl
    T, O, H, L, C = [], [], [], [], []
    for i in range(n):
        t, o, h, l, c = struct.unpack_from("<qdddd", d, off + 60 * i)
        T.append(t); O.append(o); H.append(h); L.append(l); C.append(c)
    return T, O, H, L, C

NAN = float("nan")
def isn(x): return x != x

def src(b, s):
    T, O, H, L, C = b
    if s == "close": return list(C)
    if s == "open": return list(O)
    if s == "high": return list(H)
    if s == "low": return list(L)
    if s == "median": return [(H[i] + L[i]) / 2 for i in range(len(C))]
    if s == "typical": return [(H[i] + L[i] + C[i]) / 3 for i in range(len(C))]

def sma(x, p):
    o = [NAN] * len(x)
    for i in range(len(x)):
        w = x[max(0, i - p + 1): i + 1]
        if len(w) == p and not any(isn(v) for v in w): o[i] = sum(w) / p
    return o

def ema(x, p):
    o = [NAN] * len(x); a = 2 / (p + 1); prev = None
    for i in range(len(x)):
        w = x[max(0, i - p + 1): i + 1]
        if prev is None:
            if len(w) == p and not any(isn(v) for v in w): prev = sum(w) / p; o[i] = prev
        elif not isn(x[i]):
            prev = prev + a * (x[i] - prev); o[i] = prev
    return o

def tr_of(b):
    T, O, H, L, C = b; r = []
    for i in range(len(C)):
        v = H[i] - L[i]
        if i: v = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
        r.append(v)
    return r

def hh(x, p): return [max(x[i - p + 1: i + 1]) if i >= p - 1 else NAN for i in range(len(x))]
def ll(x, p): return [min(x[i - p + 1: i + 1]) if i >= p - 1 else NAN for i in range(len(x))]

def calc(b, name, out, source, P):
    T, O, H, L, C = b; n = len(C); x = src(b, source)
    if name == "SMA": return sma(x, P["period"])
    if name == "EMA": return ema(x, P["period"])
    if name == "RSI":
        p = P["period"]; r = [NAN] * n
        gains = [0.0] + [max(x[i] - x[i - 1], 0) for i in range(1, n)]
        loss = [0.0] + [max(x[i - 1] - x[i], 0) for i in range(1, n)]
        ag = sum(gains[1:p + 1]) / p; al = sum(loss[1:p + 1]) / p
        for i in range(p, n):
            if i > p:
                ag = (ag * (p - 1) + gains[i]) / p; al = (al * (p - 1) + loss[i]) / p
            r[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
        return r
    if name == "ATR": return sma(tr_of(b), P["period"])
    if name == "MACD":
        ef, es = ema(x, P["fast"]), ema(x, P["slow"])
        line = [NAN if isn(ef[i]) or isn(es[i]) else ef[i] - es[i] for i in range(n)]
        sg = ema(line, P["signal"])
        d = {"line": line, "signal": sg, "hist": [NAN if isn(sg[i]) else line[i] - sg[i] for i in range(n)]}
        return d[out]
    if name == "BBANDS":
        p = P["period"]; m = sma(x, p); res = {k: [NAN] * n for k in ("middle", "upper", "lower", "width", "pctb")}
        for i in range(n):
            if isn(m[i]): continue
            w = x[i - p + 1: i + 1]; sd = math.sqrt(sum((v - m[i]) ** 2 for v in w) / p)
            u, l = m[i] + P["dev"] * sd, m[i] - P["dev"] * sd
            res["middle"][i] = m[i]; res["upper"][i] = u; res["lower"][i] = l
            res["width"][i] = (u - l) / m[i]; res["pctb"][i] = (x[i] - l) / (u - l) if u != l else 0.5
        return res[out]
    if name == "DONCHIAN":
        u, l = hh(H, P["period"]), ll(L, P["period"])
        return {"upper": u, "lower": l, "mid": [NAN if isn(u[i]) else (u[i] + l[i]) / 2 for i in range(n)]}[out]
    if name == "STOCH":
        H_, L_ = hh(H, P["k_period"]), ll(L, P["k_period"])
        raw = [NAN if isn(H_[i]) else (50.0 if H_[i] == L_[i] else 100 * (C[i] - L_[i]) / (H_[i] - L_[i])) for i in range(n)]
        k = sma(raw, P["k_smooth"]); return {"k": k, "d": sma(k, P["d_period"])}[out]
    if name == "CCI":
        p = P["period"]; tp = [(H[i] + L[i] + C[i]) / 3 for i in range(n)]; m = sma(tp, p); r = [NAN] * n
        for i in range(n):
            if isn(m[i]): continue
            md = sum(abs(v - m[i]) for v in tp[i - p + 1: i + 1]) / p
            r[i] = 0.0 if md == 0 else (tp[i] - m[i]) / (0.015 * md)
        return r
    if name == "ROC":
        p = P["period"]; return [NAN if i < p or x[i - p] == 0 else 100 * (x[i] / x[i - p] - 1) for i in range(n)]
    if name == "WILLR":
        H_, L_ = hh(H, P["period"]), ll(L, P["period"])
        return [NAN if isn(H_[i]) else (-50.0 if H_[i] == L_[i] else -100 * (H_[i] - C[i]) / (H_[i] - L_[i])) for i in range(n)]
    if name == "ADX":
        p = P["period"]; tr = tr_of(b); pdm = [0.0] * n; mdm = [0.0] * n
        for i in range(1, n):
            up, dn = H[i] - H[i - 1], L[i - 1] - L[i]
            pdm[i] = up if (up > dn and up > 0) else 0.0
            mdm[i] = dn if (dn > up and dn > 0) else 0.0
        sT, sP, sM = sum(tr[1:p + 1]), sum(pdm[1:p + 1]), sum(mdm[1:p + 1])
        pdi, mdi, dx = [NAN] * n, [NAN] * n, [NAN] * n
        for i in range(p, n):
            if i > p:
                sT = sT - sT / p + tr[i]; sP = sP - sP / p + pdm[i]; sM = sM - sM / p + mdm[i]
            pdi[i] = 100 * sP / sT if sT > 0 else 0.0; mdi[i] = 100 * sM / sT if sT > 0 else 0.0
            s = pdi[i] + mdi[i]; dx[i] = 100 * abs(pdi[i] - mdi[i]) / s if s > 0 else 0.0
        adx = [NAN] * n; a = sum(dx[p:2 * p]) / p; adx[2 * p - 1] = a
        for i in range(2 * p, n):
            a = (a * (p - 1) + dx[i]) / p; adx[i] = a
        return {"adx": adx, "plus_di": pdi, "minus_di": mdi}[out]
    raise SystemExit("нет проверки для " + name)

CASES = [
    ("SMA", "value", "close", {"period": 20}), ("SMA", "value", "typical", {"period": 7}),
    ("EMA", "value", "close", {"period": 50}), ("EMA", "value", "median", {"period": 5}),
    ("RSI", "value", "close", {"period": 14}), ("RSI", "value", "close", {"period": 8}),
    ("ATR", "value", "close", {"period": 14}),
    ("MACD", "line", "close", {"fast": 12, "slow": 26, "signal": 9}), ("MACD", "signal", "close", {"fast": 12, "slow": 26, "signal": 9}),
    ("MACD", "hist", "close", {"fast": 5, "slow": 13, "signal": 5}),
    ("BBANDS", "upper", "close", {"period": 20, "dev": 2.0}), ("BBANDS", "lower", "close", {"period": 20, "dev": 2.0}),
    ("BBANDS", "width", "close", {"period": 20, "dev": 2.0}), ("BBANDS", "pctb", "close", {"period": 10, "dev": 1.5}),
    ("DONCHIAN", "upper", "close", {"period": 20}), ("DONCHIAN", "lower", "close", {"period": 55}), ("DONCHIAN", "mid", "close", {"period": 10}),
    ("STOCH", "k", "close", {"k_period": 14, "k_smooth": 3, "d_period": 3}), ("STOCH", "d", "close", {"k_period": 5, "k_smooth": 3, "d_period": 3}),
    ("CCI", "value", "close", {"period": 20}), ("CCI", "value", "close", {"period": 5}),
    ("ROC", "value", "close", {"period": 10}), ("WILLR", "value", "close", {"period": 14}),
    ("ADX", "adx", "close", {"period": 14}), ("ADX", "plus_di", "close", {"period": 14}), ("ADX", "minus_di", "close", {"period": 7}),
]

if __name__ == "__main__":
    tester, path = sys.argv[1], sys.argv[2]
    keep = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    b = load(path)
    if keep:
        b = tuple(v[-keep:] for v in b)
        # тестер читает файл целиком; сравниваем только последние keep значений (прогрев уже набран)
    bad = 0
    for name, out, source, P in CASES:
        args = [tester, "--dump", path, name, out, source] + [f"{k}={v}" for k, v in P.items()]
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode: print("ОШИБКА тестера:", name, res.stderr.strip()); bad += 1; continue
        vals = [float(l.split()[1]) for l in res.stdout.splitlines()]
        full = load(path)
        mine = calc(full, name, out, source, P)
        assert len(vals) == len(mine)
        maxd, cnt, nanmis = 0.0, 0, 0
        for i in range(len(vals)):
            a, c = vals[i], mine[i]
            if isn(a) != isn(c): nanmis += 1; continue
            if isn(a): continue
            cnt += 1; d = abs(a - c); maxd = max(maxd, d / max(1.0, abs(c)))
        ok = nanmis == 0 and maxd < 1e-7 and cnt > 0
        bad += 0 if ok else 1
        print(f"{'OK ' if ok else 'ОШИБКА'} {name}.{out} {source} {P}: значений {cnt}, расхождение NaN {nanmis}, макс.отн.расхождение {maxd:.2e}")
    print("ИТОГ:", "ВСЕ СОВПАЛИ" if bad == 0 else f"ЕСТЬ РАСХОЖДЕНИЯ: {bad}")
    sys.exit(1 if bad else 0)
