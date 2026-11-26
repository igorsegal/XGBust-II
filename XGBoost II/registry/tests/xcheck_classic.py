# Независимая проверка CLASSIC_TRACE_01: правило пересчитывается на Python по тексту registry/specs/CLASSIC_TRACE_01.md
# (сначала все уровни и свечи, на которых они пропадают, потом выносы, потом ордера) и сравнивается с тестером.
# Использование: python xcheck_classic.py <tester> <registry/configs/classic_trace_XXX_M5.json> [папка BAZA]
import sys, os, json, csv, subprocess, tempfile, bisect
import xcheck_common as X

RID = 'CLASSIC_TRACE_01'
tester, cfg_path = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
cfg = json.load(open(cfg_path, encoding='utf-8-sig'))
if len(sys.argv) > 3: cfg['data']['bars_dir'] = sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__))
reg = json.load(open(os.path.join(here, '..', 'rules_registry.json'), encoding='utf-8-sig'))
rule = next(r for r in reg['rules'] if r['id'] == RID)
P = {k: v['default'] for k, v in rule['params'].items()}
P.update(cfg['rules'][RID].get('params', {}))
pair, bdir = cfg['data']['pair'], cfg['data']['bars_dir']

with tempfile.TemporaryDirectory(dir=here) as tmp:
    cfg['output'] = os.path.join(tmp, 'res.json'); cfg['registry'] = os.path.join(here, '..', 'rules_registry.json')
    c2 = os.path.join(tmp, 'cfg.json'); json.dump(cfg, open(c2, 'w', encoding='utf-8'))
    tcsv = os.path.join(tmp, 'trades.csv')
    r = subprocess.run([tester, c2, '--trades=' + tcsv], capture_output=True)
    if r.returncode: print(r.stderr.decode('utf-8', 'replace')); sys.exit(2)
    with open(cfg['output'], encoding='utf-8') as fh: res = json.load(fh)
    with open(tcsv) as fh: theirs = list(csv.DictReader(fh))

path = lambda tf: os.path.join(bdir, pair, f'{pair}_{tf}.bin')
M, H = X.load(path('M5'), X.DEV_CUT), X.load(path('H1'), X.DEV_CUT)
T, O, Hi, Lo, C, SP, pt = M['T'], M['O'], M['H'], M['L'], M['C'], M['SP'], M['pt']; n = len(T)

def true_range(B):
    h, l, c = B['H'], B['L'], B['C']
    return [h[0] - l[0]] + [max(h[i], c[i - 1]) - min(l[i], c[i - 1]) for i in range(1, len(c))]

TR = true_range(M); acc = [0.0]
for v in TR: acc.append(acc[-1] + v)
mean_tr = lambda i, p: None if i + 1 < p else (acc[i + 1] - acc[i + 1 - p]) / p

def structure(B):
    """Все уровни таймфрейма (номер свечи появления, нижняя, верхняя граница) и направление после каждой свечи."""
    o, h, l, c, sp = B['O'], B['H'], B['L'], B['C'], B['SP']; N = P['fractal_n']; m = len(c)
    swing_hi = {k for k in range(N, m - N) if h[k] > max(h[k - N:k]) and h[k] > max(h[k + 1:k + N + 1])}
    swing_lo = {k for k in range(N, m - N) if l[k] < min(l[k - N:k]) and l[k] < min(l[k + 1:k + N + 1])}
    out = dict(ob_buy=[], ob_sell=[], eq_low=[], eq_high=[]); bias = []; hs = []; ls = []; used_h = used_l = False; state = 0
    last_bear = []; last_bull = []; lb = lu = -1
    for i in range(m):
        last_bear.append(lb); last_bull.append(lu)          # последняя свеча нужного цвета строго до i
        if c[i] < o[i]: lb = i
        if c[i] > o[i]: lu = i
        k = i - N; tol = P['eq_spread_mult'] * sp[i] * B['pt'] + 1e-9 * B['pt']
        if k in swing_hi:
            if hs and abs(h[k] - hs[-1]) <= tol: out['eq_high'].append((i, min(h[k], hs[-1]), max(h[k], hs[-1])))
            hs.append(h[k]); used_h = False
        if k in swing_lo:
            if ls and abs(l[k] - ls[-1]) <= tol: out['eq_low'].append((i, min(l[k], ls[-1]), max(l[k], ls[-1])))
            ls.append(l[k]); used_l = False
        up = bool(hs) and c[i] > hs[-1]; dn = bool(ls) and c[i] < ls[-1]
        if up or dn: state = 0 if (up and dn) else (1 if up else -1)
        if up and not used_h:
            used_h = True; a = last_bear[i]
            if a >= 0 and any(l[j + 1] > h[j - 1] for j in range(a + 1, i)): out['ob_buy'].append((i, l[a], h[a]))
        if dn and not used_l:
            used_l = True; a = last_bull[i]
            if a >= 0 and any(h[j + 1] < l[j - 1] for j in range(a + 1, i)): out['ob_sell'].append((i, l[a], h[a]))
        b = 0
        if state == 1 and len(ls) > 1 and ls[-1] > ls[-2]: b = 1
        if state == -1 and len(hs) > 1 and hs[-1] < hs[-2]: b = -1
        bias.append(b)
    return out, bias

Z5, _ = structure(M); Z1, bias1 = structure(H)
h_close = [t + 3600 for t in H['T']]

# первая свеча M5, начиная с start, задевающая уровень (поиск блоками)
BL = 512
lo_blk = [min(Lo[i:i + BL]) for i in range(0, n, BL)]; hi_blk = [max(Hi[i:i + BL]) for i in range(0, n, BL)]
def first_hit(start, arr, blk, test):
    i = start
    while i < n:
        if i % BL == 0 and not test(blk[i // BL]): i += BL; continue
        if test(arr[i]): return i
        i += 1
    return n
def death(kind, start, lo, hi):
    if kind == 'ob_buy': return first_hit(start, Lo, lo_blk, lambda v: v <= hi)
    if kind == 'ob_sell': return first_hit(start, Hi, hi_blk, lambda v: v >= lo)
    if kind == 'eq_low': return first_hit(start, Lo, lo_blk, lambda v: v < lo)
    return first_hit(start, Hi, hi_blk, lambda v: v > hi)

L5 = {k: [(c, death(k, c + 1, lo, hi), lo, hi) for c, lo, hi in v] for k, v in Z5.items()}                       # c - свеча появления
L1 = {k: [(h_close[c], death(k, bisect.bisect_left(T, h_close[c]), lo, hi), lo, hi) for c, lo, hi in v] for k, v in Z1.items()}

def target(side, price, now, idx):
    """Ближайший уровень H1, появившийся не позже now и не тронутый свечами до idx (не включая)."""
    vals = []
    if side == 1:
        for k in ('ob_sell', 'eq_high'): vals += [lo for born, d, lo, hi in L1[k] if born <= now and d >= idx and lo > price]
        return min(vals) if vals else None
    for k in ('ob_buy', 'eq_low'): vals += [hi for born, d, lo, hi in L1[k] if born <= now and d >= idx and hi < price]
    return max(vals) if vals else None

start_t = X.dev_windows(T[0])[0][1]; first = bisect.bisect_left(T, start_t)
F = {k: 0 for k in res['rules'][0]['funnel']}
def count(key, i):
    if i >= first: F[key] += 1

def triangle(i):
    a3 = mean_tr(i, P['tri_atr_bars'])
    if a3 is None: return False
    for size in range(P['tri_min_bars'], P['tri_max_bars'] + 1):
        a = i - size + 1
        if a < 0: return False
        mid = a + size // 2
        h1, h2, l1, l2 = max(Hi[a:mid]), max(Hi[mid:i + 1]), min(Lo[a:mid]), min(Lo[mid:i + 1])
        if h2 < h1 and l2 > l1 and a3 / (h1 - l1) <= P['tri_atr_max'] + 1e-9: return True
    return False

# --- выносы и возвраты: зависят только от цены ---
in_window = lambda i: P['window_start_min'] * 60 <= T[i] % 86400 < P['window_end_min'] * 60
cands = []; i = max(P['apex_bars'], P['tri_max_bars'])
while i < n:
    if not in_window(i): i += 1; continue
    kh = bisect.bisect_right(h_close, T[i]) - 1
    side = bias1[kh] if kh >= 0 else 0
    a = mean_tr(i - 1, P['atr_period'])
    if not side or not a: i += 1; continue
    prev = range(i - P['apex_bars'], i)
    edge = min(Lo[k] for k in prev) if side == 1 else max(Hi[k] for k in prev)
    pierce = Lo[i] < edge if side == 1 else Hi[i] > edge
    if not pierce or not triangle(i - 1): i += 1; continue
    count('breakouts', i)
    j = i; outside = 0; peak = i; ext = Lo[i] if side == 1 else Hi[i]; day = T[i] // 86400
    while j < n and in_window(j) and T[j] // 86400 == day:
        v = Lo[j] if side == 1 else Hi[j]
        if side * (ext - v) > 0: ext, peak = v, j
        back = side * (C[j] - edge) > 0
        if not back: outside += 1
        depth = side * (edge - ext)
        if depth > P['sweep_max_atr'] * a + 1e-12 or outside > P['max_outside']: count('true_moves', j); j += 1; break
        if back:
            if depth >= P['sweep_min_atr'] * a - 1e-12 and j >= first - 1:
                cands.append(dict(i=j, b=i, dir=side, ext=ext, peak=peak, atr=a))
            j += 1; break
        j += 1
    i = max(j, i + 1)

# --- средний спред часа ---
hist = {u: [] for u in range(24)}; cur = {}; curday = None
for k in range(n):
    d = T[k] // 86400
    if d != curday:
        for u, sc in cur.items(): hist[u].append((d if curday is None else curday, sc))
        cur = {}; curday = d
    u = T[k] % 86400 // 3600; s, c = cur.get(u, (0, 0)); cur[u] = (s + SP[k], c + 1)
for u, sc in cur.items(): hist[u].append((curday, sc))
hdays = {u: [d for d, _ in v] for u, v in hist.items()}
def usual_spread(d, u):
    k = bisect.bisect_left(hdays[u], d); prev = hist[u][max(0, k - P['spread_days']):k]
    return None if not prev else sum(s for _, (s, _) in prev) / sum(c for _, (_, c) in prev)

# --- ордера и сделки ---
lot = 100000; trades = []; busy = -1
def losses_on(day): return sum(1 for t in trades if t['pnl'] < 0 and T[t['out']] // 86400 == day)

def manage(side, e, entry, sl, tp, sig, limit, intrabar):
    half = entry + P['be_fraction'] * (tp - entry); be_price = entry + side * SP[e] * pt; stop = sl; moved = False
    for k in range(e, n):
        add = 0 if side == 1 else SP[k] * pt
        o, worst, best = O[k] + add, (Lo[k] if side == 1 else Hi[k]) + add, (Hi[k] if side == 1 else Lo[k]) + add
        full = not (intrabar and k == e)
        if k > e and side * (o - stop) <= 0: px, why = o, 'BE' if moved else 'SL'; break
        if side * (worst - stop) <= 0: px, why = stop, 'BE' if moved else 'SL'; break
        if full and side * (best - tp) >= 0: px, why = tp, 'TP'; break
        if full and not moved and side * (best - half) >= 0: moved = True; stop = be_price
    else:
        k = n - 1; px, why = (C[k] if side == 1 else C[k] + SP[k] * pt), 'END'
    comm = 7 / lot * (1 if pair.endswith('USD') else entry)
    trades.append(dict(sig=sig, e=e, out=k, dir=side, entry=entry, exit=px, sl=sl, tp=tp, pnl=side * (px - entry) - comm, why=why, be=int(moved), limit=limit))
    return n if why == 'END' else k

def rr_ok(side, price, sl, tp):
    risk, gain = side * (price - sl), side * (tp - price)
    return risk > 0 and gain > 0 and gain / risk >= P['min_rr'] - 1e-9

for s in cands:
    j, side = s['i'], s['dir']; count('returns', j)
    usual = usual_spread(T[j] // 86400, T[j] % 86400 // 3600)
    if usual is None or SP[j] > P['spread_mult'] * usual + 1e-12: count('rej_spread', j); continue
    if j < busy: count('rej_busy', j); continue
    if losses_on(T[j] // 86400) >= P['max_losses']: count('rej_losses', j); continue
    if j + 1 >= n: continue
    b = s['b']; ext = s['ext']
    obs = L5['ob_buy' if side == 1 else 'ob_sell']; eqs = L5['eq_low' if side == 1 else 'eq_high']
    mark = any(born < b and d >= b and (ext <= hi if side == 1 else ext >= lo) for born, d, lo, hi in obs) or \
           any(born < b and d >= b and (ext < lo if side == 1 else ext > hi) for born, d, lo, hi in eqs)
    sl = ext - side * (SP[j] * pt + P['sl_buffer_atr'] * s['atr'])
    if mark:
        count('landmark', j); e = j + 1; busy = e
        if T[e] - (T[j] + 300) > P['max_entry_gap_min'] * 60: count('rej_gap', e); continue
        if losses_on(T[e] // 86400) >= P['max_losses']: count('rej_losses', e); continue
        entry = O[e] + SP[e] * pt if side == 1 else O[e]
        tp = target(side, entry, T[e], e)
        if tp is None: count('rej_target', e); continue
        if not rr_ok(side, entry, sl, tp): count('rej_rr', e); continue
        count('entries_market', e); busy = manage(side, e, entry, sl, tp, j, 0, False)
        continue
    p = s['peak']; price = O[p] + P['limit_body_part'] * (C[p] - O[p])
    tp = target(side, price, T[j] + 300, j + 1)
    if tp is None: count('rej_target', j); continue
    if not rr_ok(side, price, sl, tp): count('rej_rr', j); continue
    count('limit_placed', j); busy = n
    for k in range(j + 1, n):
        ask = SP[k] * pt
        stop_gap = O[k] <= sl if side == 1 else O[k] + ask >= sl
        at_open = (O[k] + ask <= price) if side == 1 else (O[k] >= price)
        touched = (Lo[k] + ask <= price) if side == 1 else (Hi[k] >= price)
        if stop_gap: count('limit_dropped', k); busy = k; break
        if at_open or touched:
            if losses_on(T[k] // 86400) >= P['max_losses']: count('limit_dropped', k); busy = k; break
            entry = (O[k] + ask if side == 1 else O[k]) if at_open else price
            count('entries_limit', k); busy = manage(side, k, entry, sl, tp, j, 1, not at_open); break
        if k - j >= P['limit_ttl_bars']: count('limit_dropped', k); busy = k; break

bad = 0
if len(trades) != len(theirs): bad += 1; print(f'ОШИБКА: сделок Python {len(trades)}, тестер {len(theirs)}')
mine = {T[t['e']]: t for t in trades}; other = {int(t['entry_time']): t for t in theirs}
only_m, only_t = sorted(set(mine) - set(other)), sorted(set(other) - set(mine))
if only_m or only_t: bad += 1; print('ОШИБКА: входы только в Python', len(only_m), only_m[:5], '; только в тестере', len(only_t), only_t[:5])
diff = 0
for key in sorted(set(mine) & set(other)):
    a, b = mine[key], other[key]
    ok = (T[a['sig']] == int(b['signal_time']) and T[a['out']] == int(b['exit_time']) and a['dir'] == int(b['dir'])
          and a['why'] == b['why'] and a['be'] == int(b['be']) and a['limit'] == int(b['limit'])
          and all(abs(a[f] - float(b[f])) < 1e-6 * max(1, abs(a[f]) * 1e-1) for f in ('entry', 'exit', 'sl', 'tp', 'pnl')))
    if not ok:
        diff += 1
        if diff <= 5: print('ОШИБКА сделка', key, a, b)
bad += diff > 0
for k, v in res['rules'][0]['funnel'].items():
    if F[k] != v: bad += 1; print(f'ОШИБКА: {k}: Python {F[k]}, тестер {v}')
print(f"{'OK ' if not diff else 'ОШИБКА'} {pair}: сделок сверено {len(set(mine) & set(other))}, расхождений {diff}")
bad += X.compare(res, [(T[t['e']], t['pnl'] / (10 * pt)) for t in trades], T[0])
sys.exit(1 if bad else 0)
