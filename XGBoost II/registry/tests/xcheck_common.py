# Общая часть независимых проверок тестера: чтение баров, окна, симуляция сделок. Код отдельный от C++.
import struct, json, os, sys, datetime as dt

UTC = dt.timezone.utc

def load(path, cutoff):
    """Бары, закрывшиеся не позже cutoff."""
    b = open(path, 'rb').read(); per, = struct.unpack('<i', b[16:20]); pt, = struct.unpack('<d', b[24:32])
    n, = struct.unpack('<q', b[32:40]); sl, = struct.unpack('<i', b[56:60]); off = 60 + sl
    R = [r for r in struct.iter_unpack('<qddddqiq', b[off:off + 60 * n]) if r[0] + per <= cutoff]
    col = lambda k: [r[k] for r in R]
    return dict(pt=pt, per=per, T=col(0), O=col(1), H=col(2), L=col(3), C=col(4), V=col(5), SP=col(6))

def month(y, m, k=0):
    v = y * 12 + m - 1 + k
    return int(dt.datetime(v // 12, v % 12 + 1, 1, tzinfo=UTC).timestamp())

def dev_windows(first_bar):
    """Окна разработки: обучение 6 месяцев, проверка 2, с января 2020 по декабрь 2024."""
    out = []
    for k in range(27):
        train, test = month(2020, 1, 2 * k), month(2020, 7, 2 * k)
        if first_bar <= train + 5 * 86400: out.append((k + 1, test, month(2020, 9, 2 * k)))
    return out

DEV_CUT = month(2025, 1)

def trades(B, sig, pair, start, hold=24, mult=2):
    O, H, L, C, SP, T, pt = B['O'], B['H'], B['L'], B['C'], B['SP'], B['T'], B['pt']; n = len(C)
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
    atr = [None] * n
    for i in range(13, n): atr[i] = sum(tr[i - 13:i + 1]) / 14
    lot = 100 if pair.startswith('XAU') else 100000
    first = next(i for i in range(n) if T[i] >= start)
    free = 0; out = []
    for x in range(n - 1):
        if not sig[x] or x + 1 < first or x < free or atr[x] is None: continue
        e = x + 1
        if e + hold - 1 >= n: break
        d = mult * atr[x]; sp = SP[e] * pt; dr = sig[x]
        entry = O[e] + sp if dr > 0 else O[e]; stop = entry - d if dr > 0 else entry + d; ex = None
        for k in range(e, e + hold):
            if dr > 0:
                if k > e and O[k] <= stop: ex = O[k]; break
                if L[k] <= stop: ex = stop; break
            else:
                ao = O[k] + SP[k] * pt; ah = H[k] + SP[k] * pt
                if k > e and ao >= stop: ex = ao; break
                if ah >= stop: ex = stop; break
        if ex is None: k = e + hold - 1; ex = C[k] if dr > 0 else C[k] + SP[k] * pt
        comm = 7 / lot * (1 if pair.endswith('USD') else entry)     # котировка не в долларах: перевод по цене входа
        pnl = (ex - entry if dr > 0 else entry - ex) - comm
        out.append((T[e], pnl / (10 * pt))); free = k
    return out

def compare(res, tr, first_bar):
    """Сравнить итог и каждое окно с результатом тестера. Возвращает код выхода."""
    W = dev_windows(first_bar); rule = res['rules'][0]; seg = rule['segments'][0]; bad = 0
    ps = [p for t, p in tr if W[0][1] <= t < W[-1][2]]
    gw = sum(p for p in ps if p > 0); gl = -sum(p for p in ps if p < 0); f = gw / gl if gl else (999 if gw > 0 else 0)
    ok = seg['segment'] == 'dev' and len(ps) == seg['trades'] and abs(sum(ps) - seg['net_pips']) < 0.11 and abs(f - seg['profit_factor']) < 0.002
    bad += not ok
    print(f"{'OK ' if ok else 'ОШИБКА'} {res['test_name']}: Python сделок {len(ps)}, нетто {sum(ps):.1f}, PF {f:.3f}  |  тестер сделок {seg['trades']}, нетто {seg['net_pips']}, PF {seg['profit_factor']}")
    if [w['n'] for w in rule['windows']] != [w[0] for w in W]: bad += 1; print('ОШИБКА: другой набор окон')
    wbad = 0
    for (num, a, b), r in zip(W, rule['windows']):
        q = [p for t, p in tr if a <= t < b]
        wbad += not (len(q) == r['trades'] and abs(sum(q) - r['net_pips']) < 0.11)
    print(f"{'OK ' if not wbad else 'ОШИБКА'} окон сверено {len(W)}, расхождений {wbad}")
    return 1 if bad or wbad else 0
