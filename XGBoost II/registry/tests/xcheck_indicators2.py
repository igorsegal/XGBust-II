#!/usr/bin/env python3
"""xcheck_indicators2.py - независимая проверка остальных индикаторов справочника (вторая часть).
Каждый индикатор пересчитывается на Python по тексту формулы из indicators_catalog.json и сравнивается с `tester --dump`.
Время (час, день недели, неделя, сутки) считается стандартной библиотекой datetime, а не арифметикой тестера.
Использование: python xcheck_indicators2.py <tester> <файл баров XFBAR001>"""
import struct, subprocess, sys, math, datetime
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from xcheck_indicators import sma, ema, tr_of, hh, ll, src, isn, NAN

def trade_day(d):
    """Дата бара для пивотов и VWAP: воскресенье считается понедельником."""
    return (d + datetime.timedelta(days=1)).date() if d.weekday() == 6 else d.date()

def loadv(path):
    d = open(path, "rb").read(); n = struct.unpack_from("<q", d, 32)[0]; sl = struct.unpack_from("<i", d, 56)[0]
    per = struct.unpack_from("<i", d, 16)[0]; off = 60 + sl
    T, O, H, L, C, V = [], [], [], [], [], []
    for i in range(n):
        t, o, h, l, c, tv = struct.unpack_from("<qddddq", d, off + 60 * i)
        T.append(t); O.append(o); H.append(h); L.append(l); C.append(c); V.append(float(tv))
    return (T, O, H, L, C), V, per

def wma(x, p):
    o = [NAN] * len(x); den = p * (p + 1) / 2
    for i in range(len(x)):
        w = x[max(0, i - p + 1): i + 1]
        if len(w) == p and not any(isn(v) for v in w): o[i] = sum(v * (k + 1) for k, v in enumerate(w)) / den
    return o

def linreg(y, p):
    sl, ev, r2 = [NAN] * len(y), [NAN] * len(y), [NAN] * len(y)
    for i in range(p - 1, len(y)):
        w = y[i - p + 1: i + 1]
        if any(isn(v) for v in w): continue
        xs = list(range(p)); mx = sum(xs) / p; my = sum(w) / p
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, w)); sxx = sum((a - mx) ** 2 for a in xs); syy = sum((b - my) ** 2 for b in w)
        s = sxy / sxx; sl[i] = s; ev[i] = my + s * (p - 1 - mx); r2[i] = sxy * sxy / (sxx * syy) if syy > 0 else 0.0
    return sl, ev, r2

def calc(b, V, per, name, out, source, P):
    T, O, H, L, C = b; n = len(C); x = src(b, source)
    tp = [(H[i] + L[i] + C[i]) / 3 for i in range(n)]
    dts = [datetime.datetime.fromtimestamp(t, datetime.timezone.utc) for t in T]
    if name == "WMA": return wma(x, P["period"])
    if name == "HMA":
        p = P["period"]; h = max(1, p // 2); q = max(1, int(math.floor(math.sqrt(p) + 0.5)))
        a, c = wma(x, h), wma(x, p); d = [NAN if isn(a[i]) or isn(c[i]) else 2 * a[i] - c[i] for i in range(n)]
        return wma(d, q)
    if name == "MFI":
        p = P["period"]; r = [NAN] * n
        for i in range(p, n):
            pos = neg = 0.0
            for j in range(i - p + 1, i + 1):
                f = tp[j] * V[j]
                if tp[j] > tp[j - 1]: pos += f
                elif tp[j] < tp[j - 1]: neg += f
            r[i] = (50.0 if pos == 0 else 100.0) if neg == 0 else 100 - 100 / (1 + pos / neg)
        return r
    if name == "MOMENTUM": return [NAN if i < P["period"] else x[i] - x[i - P["period"]] for i in range(n)]
    if name == "CMO":
        p = P["period"]; r = [NAN] * n
        for i in range(p, n):
            ch = [x[j] - x[j - 1] for j in range(i - p + 1, i + 1)]; u = sum(c for c in ch if c > 0); d = -sum(c for c in ch if c < 0)
            r[i] = 0.0 if u + d == 0 else 100 * (u - d) / (u + d)
        return r
    if name == "ULTIMATE":
        bp = [NAN] + [C[i] - min(L[i], C[i - 1]) for i in range(1, n)]; tr = [NAN] + [max(H[i], C[i - 1]) - min(L[i], C[i - 1]) for i in range(1, n)]
        r = [NAN] * n
        for i in range(P["p3"], n):
            av = []
            for pk in (P["p1"], P["p2"], P["p3"]):
                sb = sum(bp[i - pk + 1: i + 1]); st = sum(tr[i - pk + 1: i + 1]); av.append(0.0 if st == 0 else sb / st)
            r[i] = 100 * (4 * av[0] + 2 * av[1] + av[2]) / 7
        return r
    if name == "TSI":
        m = [NAN] + [x[i] - x[i - 1] for i in range(1, n)]; am = [NAN if isn(v) else abs(v) for v in m]
        nu = ema(ema(m, P["long_period"]), P["short_period"]); de = ema(ema(am, P["long_period"]), P["short_period"])
        return [NAN if isn(nu[i]) or isn(de[i]) else (0.0 if de[i] == 0 else 100 * nu[i] / de[i]) for i in range(n)]
    if name == "KELTNER":
        mid = ema(x, P["period"]); at = sma(tr_of(b), P["atr_period"]); r = {"middle": [NAN] * n, "upper": [NAN] * n, "lower": [NAN] * n}
        for i in range(n):
            if isn(mid[i]) or isn(at[i]): continue
            r["middle"][i] = mid[i]; r["upper"][i] = mid[i] + P["mult"] * at[i]; r["lower"][i] = mid[i] - P["mult"] * at[i]
        return r[out]
    if name == "STDDEV":
        p = P["period"]; r = [NAN] * n
        for i in range(p - 1, n):
            w = x[i - p + 1: i + 1]; m = sum(w) / p; r[i] = math.sqrt(sum((v - m) ** 2 for v in w) / p)
        return r
    if name == "PARKINSON":
        m = sma([math.log(H[i] / L[i]) ** 2 for i in range(n)], P["period"]); return [NAN if isn(v) else math.sqrt(v / (4 * math.log(2))) for v in m]
    if name == "GARMAN_KLASS":
        t = [0.5 * math.log(H[i] / L[i]) ** 2 - (2 * math.log(2) - 1) * math.log(C[i] / O[i]) ** 2 for i in range(n)]
        m = sma(t, P["period"]); return [NAN if isn(v) else math.sqrt(max(0.0, v)) for v in m]
    if name == "AROON":
        p = P["period"]; up, dn = [NAN] * n, [NAN] * n
        for i in range(p, n):
            wh = H[i - p: i + 1]; wl = L[i - p: i + 1]
            ih = max(j for j in range(p + 1) if wh[j] == max(wh)); il = max(j for j in range(p + 1) if wl[j] == min(wl))   # самый свежий при равенстве
            up[i] = 100 * ih / p; dn[i] = 100 * il / p
        return {"up": up, "down": dn, "osc": [NAN if isn(up[i]) else up[i] - dn[i] for i in range(n)]}[out]
    if name == "PSAR":
        step, mx = P["step"], P["max_step"]; sar = [NAN] * n; dr = [NAN] * n
        lg = C[1] >= C[0]; s = L[0] if lg else H[0]; ep = H[1] if lg else L[1]; af = step; sar[1] = s; dr[1] = 1 if lg else -1
        for i in range(2, n):
            s = s + af * (ep - s)
            if lg:
                s = min(s, L[i - 1], L[i - 2])
                if L[i] < s: lg = False; s = ep; ep = L[i]; af = step
                elif H[i] > ep: ep = H[i]; af = min(af + step, mx)
            else:
                s = max(s, H[i - 1], H[i - 2])
                if H[i] > s: lg = True; s = ep; ep = H[i]; af = step
                elif L[i] < ep: ep = L[i]; af = min(af + step, mx)
            sar[i] = s; dr[i] = 1 if lg else -1
        return sar if out == "value" else dr
    if name == "SUPERTREND":
        p, m = P["period"], P["mult"]; at = sma(tr_of(b), p); line = [NAN] * n; dr = [NAN] * n; st = p - 1
        fu = fl = 0.0; tr = 0
        for i in range(st, n):
            hl2 = (H[i] + L[i]) / 2; bu = hl2 + m * at[i]; bl = hl2 - m * at[i]
            if i == st: fu, fl, tr = bu, bl, (1 if C[i] >= hl2 else -1)
            else:
                nfu = bu if (bu < fu or C[i - 1] > fu) else fu; nfl = bl if (bl > fl or C[i - 1] < fl) else fl
                if tr == -1 and C[i] > fu: tr = 1
                elif tr == 1 and C[i] < fl: tr = -1
                fu, fl = nfu, nfl
            line[i] = fl if tr == 1 else fu; dr[i] = tr
        return line if out == "value" else dr
    if name == "ICHIMOKU":
        def mid(p): return [NAN if i < p - 1 else (max(H[i - p + 1: i + 1]) + min(L[i - p + 1: i + 1])) / 2 for i in range(n)]
        t, k, s = mid(P["tenkan"]), mid(P["kijun"]), mid(P["senkou_b"]); kj = P["kijun"]
        sa = [NAN if i < kj or isn(t[i - kj]) or isn(k[i - kj]) else (t[i - kj] + k[i - kj]) / 2 for i in range(n)]
        sb = [NAN if i < kj or isn(s[i - kj]) else s[i - kj] for i in range(n)]
        return {"tenkan": t, "kijun": k, "span_a": sa, "span_b": sb}[out]
    if name == "VORTEX":
        p = P["period"]; tr = tr_of(b); pl, mi = [NAN] * n, [NAN] * n
        for i in range(p, n):
            vp = sum(abs(H[j] - L[j - 1]) for j in range(i - p + 1, i + 1)); vm = sum(abs(L[j] - H[j - 1]) for j in range(i - p + 1, i + 1)); s = sum(tr[i - p + 1: i + 1])
            pl[i] = vp / s if s > 0 else 0.0; mi[i] = vm / s if s > 0 else 0.0
        return pl if out == "plus" else mi
    if name == "LINREG":
        sl, ev, r2 = linreg(x, P["period"]); return {"slope": sl, "value": ev, "r2": r2}[out]
    obv = [0.0] * n
    for i in range(1, n): obv[i] = obv[i - 1] + (V[i] if C[i] > C[i - 1] else (-V[i] if C[i] < C[i - 1] else 0))
    mfv = [0.0 if H[i] == L[i] else ((C[i] - L[i]) - (H[i] - C[i])) / (H[i] - L[i]) * V[i] for i in range(n)]
    if name == "OBV": return obv
    if name == "OBV_SLOPE":
        p = P["period"]; vm = sma(V, p); sl, _, _ = linreg(obv, p)
        return [NAN if isn(vm[i]) or isn(sl[i]) else (sl[i] / vm[i] if vm[i] > 0 else 0.0) for i in range(n)]
    if name == "VOLRATIO":
        vm = sma(V, P["period"]); return [NAN if isn(vm[i]) else (V[i] / vm[i] if vm[i] > 0 else 1.0) for i in range(n)]
    if name == "AD":
        r, s = [], 0.0
        for v in mfv: s += v; r.append(s)
        return r
    if name == "CMF":
        p = P["period"]; r = [NAN] * n
        for i in range(p - 1, n):
            sv = sum(V[i - p + 1: i + 1]); r[i] = sum(mfv[i - p + 1: i + 1]) / sv if sv > 0 else 0.0
        return r
    if name == "VWAP_SESSION":
        vw, ds, cd, cpv, cv = [], [], None, 0.0, 0.0
        for i in range(n):
            if trade_day(dts[i]) != cd: cd = trade_day(dts[i]); cpv = cv = 0.0
            cpv += tp[i] * V[i]; cv += V[i]; w = cpv / cv if cv > 0 else tp[i]; vw.append(w); ds.append(C[i] - w)
        return vw if out == "vwap" else ds
    if name == "FORCE": return ema([NAN] + [(C[i] - C[i - 1]) * V[i] for i in range(1, n)], P["period"])
    if name == "EOM":
        raw = [NAN] + [0.0 if V[i] == 0 else ((H[i] + L[i]) / 2 - (H[i - 1] + L[i - 1]) / 2) * (H[i] - L[i]) / V[i] for i in range(1, n)]
        return sma(raw, P["period"])
    if name in ("BODY_RATIO", "UPPER_SHADOW", "LOWER_SHADOW", "DOJI"):
        r = []
        for i in range(n):
            rg = H[i] - L[i]; body = abs(C[i] - O[i])
            if name == "BODY_RATIO": r.append(body / rg if rg > 0 else 0.0)
            elif name == "UPPER_SHADOW": r.append((H[i] - max(O[i], C[i])) / rg if rg > 0 else 0.0)
            elif name == "LOWER_SHADOW": r.append((min(O[i], C[i]) - L[i]) / rg if rg > 0 else 0.0)
            else: r.append(1.0 if rg > 0 and body / rg <= P["threshold"] else 0.0)
        return r
    if name == "GAP": return [NAN] + [O[i] - C[i - 1] for i in range(1, n)]
    if name == "INSIDE_BAR": return [NAN] + [1.0 if (H[i] < H[i - 1] and L[i] > L[i - 1]) else 0.0 for i in range(1, n)]
    if name == "OUTSIDE_BAR": return [NAN] + [1.0 if (H[i] > H[i - 1] and L[i] < L[i - 1]) else 0.0 for i in range(1, n)]
    if name == "ENGULFING":
        r = [NAN]
        for i in range(1, n):
            bull = C[i - 1] < O[i - 1] and C[i] > O[i] and O[i] <= C[i - 1] and C[i] >= O[i - 1]
            bear = C[i - 1] > O[i - 1] and C[i] < O[i] and O[i] >= C[i - 1] and C[i] <= O[i - 1]
            r.append(1.0 if bull else (-1.0 if bear else 0.0))
        return r
    if name == "PINBAR":
        r = []
        for i in range(n):
            body = abs(C[i] - O[i]); up = H[i] - max(O[i], C[i]); lo = min(O[i], C[i]) - L[i]
            if lo > 0 and lo >= P["ratio"] * body and up <= body: r.append(1.0)
            elif up > 0 and up >= P["ratio"] * body and lo <= body: r.append(-1.0)
            else: r.append(0.0)
        return r
    if name == "HIGHEST": return hh(H, P["period"])
    if name == "LOWEST": return ll(L, P["period"])
    if name in ("PIVOT_DAY", "PIVOT_WEEK"):
        key = (lambda d: trade_day(d)) if name == "PIVOT_DAY" else (lambda d: trade_day(d).isocalendar()[:2])
        groups = []; cur = None
        for i in range(n):
            k = key(dts[i])
            if k != cur: groups.append([i, i]); cur = k
            else: groups[-1][1] = i
        r = {k: [NAN] * n for k in ("p", "r1", "s1", "r2", "s2")}
        for gi in range(1, len(groups)):
            a, bb = groups[gi - 1]; ph = max(H[a:bb + 1]); pl = min(L[a:bb + 1]); pc = C[bb]; pv = (ph + pl + pc) / 3
            for i in range(groups[gi][0], groups[gi][1] + 1):
                r["p"][i] = pv; r["r1"][i] = 2 * pv - pl; r["s1"][i] = 2 * pv - ph; r["r2"][i] = pv + (ph - pl); r["s2"][i] = pv - (ph - pl)
        return r[out]
    if name == "HOUR": return [float(d.hour) for d in dts]
    if name == "WEEKDAY": return [float(d.weekday()) for d in dts]
    if name == "SESSION": return [float(d.hour // 8) for d in dts]
    if name == "MINUTE_OF_HOUR": return [float(d.minute) for d in dts]
    if name == "BAR_OF_DAY": return [float((d.hour * 3600 + d.minute * 60 + d.second) // per) for d in dts]
    raise SystemExit("нет проверки для " + name)

CASES = [
 ("WMA","value","close",{"period":20}),("WMA","value","typical",{"period":5}),("HMA","value","close",{"period":21}),("HMA","value","close",{"period":9}),
 ("MFI","value","close",{"period":14}),("MOMENTUM","value","close",{"period":10}),("CMO","value","close",{"period":14}),
 ("ULTIMATE","value","close",{"p1":7,"p2":14,"p3":28}),("TSI","value","close",{"long_period":25,"short_period":13}),
 ("KELTNER","middle","close",{"period":20,"atr_period":10,"mult":2.0}),("KELTNER","upper","close",{"period":20,"atr_period":10,"mult":2.0}),("KELTNER","lower","close",{"period":10,"atr_period":5,"mult":1.5}),
 ("STDDEV","value","close",{"period":20}),("PARKINSON","value","close",{"period":20}),("GARMAN_KLASS","value","close",{"period":20}),
 ("AROON","up","close",{"period":25}),("AROON","down","close",{"period":25}),("AROON","osc","close",{"period":10}),
 ("PSAR","value","close",{"step":0.02,"max_step":0.2}),("PSAR","direction","close",{"step":0.02,"max_step":0.2}),("PSAR","value","close",{"step":0.05,"max_step":0.3}),
 ("SUPERTREND","value","close",{"period":10,"mult":3.0}),("SUPERTREND","direction","close",{"period":10,"mult":3.0}),("SUPERTREND","value","close",{"period":5,"mult":1.5}),
 ("ICHIMOKU","tenkan","close",{"tenkan":9,"kijun":26,"senkou_b":52}),("ICHIMOKU","kijun","close",{"tenkan":9,"kijun":26,"senkou_b":52}),
 ("ICHIMOKU","span_a","close",{"tenkan":9,"kijun":26,"senkou_b":52}),("ICHIMOKU","span_b","close",{"tenkan":9,"kijun":26,"senkou_b":52}),
 ("VORTEX","plus","close",{"period":14}),("VORTEX","minus","close",{"period":14}),
 ("LINREG","slope","close",{"period":20}),("LINREG","value","close",{"period":20}),("LINREG","r2","close",{"period":10}),
 ("OBV","value","close",{}),("OBV_SLOPE","value","close",{"period":20}),("VOLRATIO","value","close",{"period":20}),
 ("CMF","value","close",{"period":20}),("AD","value","close",{}),("VWAP_SESSION","vwap","close",{}),("VWAP_SESSION","dist","close",{}),
 ("FORCE","value","close",{"period":13}),("EOM","value","close",{"period":14}),
 ("BODY_RATIO","value","close",{}),("UPPER_SHADOW","value","close",{}),("LOWER_SHADOW","value","close",{}),("DOJI","value","close",{"threshold":0.1}),
 ("GAP","value","close",{}),("INSIDE_BAR","value","close",{}),("OUTSIDE_BAR","value","close",{}),("ENGULFING","value","close",{}),("PINBAR","value","close",{"ratio":2.0}),
 ("HIGHEST","value","close",{"period":20}),("LOWEST","value","close",{"period":50}),
 ("PIVOT_DAY","p","close",{}),("PIVOT_DAY","r1","close",{}),("PIVOT_DAY","s2","close",{}),("PIVOT_WEEK","p","close",{}),("PIVOT_WEEK","r2","close",{}),("PIVOT_WEEK","s1","close",{}),
 ("HOUR","value","close",{}),("WEEKDAY","value","close",{}),("SESSION","value","close",{}),("MINUTE_OF_HOUR","value","close",{}),("BAR_OF_DAY","value","close",{}),
]

if __name__ == "__main__":
    tester, path = sys.argv[1], sys.argv[2]; b, V, per = loadv(path); bad = 0
    for name, out, source, P in CASES:
        args = [tester, "--dump", path, name, out, source] + [f"{k}={v}" for k, v in P.items()]
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode: print("ОШИБКА тестера:", name, res.stderr.strip()); bad += 1; continue
        vals = [float(l.split()[1]) for l in res.stdout.splitlines()]; mine = calc(b, V, per, name, out, source, P)
        assert len(vals) == len(mine), (name, len(vals), len(mine))
        maxd = 0.0; cnt = 0; nanmis = 0
        for i in range(len(vals)):
            a, c = vals[i], mine[i]
            if isn(a) != isn(c): nanmis += 1; continue
            if isn(a): continue
            cnt += 1; maxd = max(maxd, abs(a - c) / max(1.0, abs(c)))
        ok = nanmis == 0 and maxd < 1e-6 and cnt > 0; bad += 0 if ok else 1
        print(f"{'OK ' if ok else 'ОШИБКА'} {name}.{out} {P}: значений {cnt}, расхождение NaN {nanmis}, макс.отн.расхождение {maxd:.2e}")
    print("ИТОГ:", "ВСЕ СОВПАЛИ" if bad == 0 else f"ЕСТЬ РАСХОЖДЕНИЯ: {bad}")
    sys.exit(1 if bad else 0)
