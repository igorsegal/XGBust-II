# Независимая проверка LONDON_TRAP_01: правило пересчитывается на Python по тексту registry/specs/LONDON_TRAP_01.md
# (по дням, а не одним проходом, как в тестере) и сравнивается с тестером сделка за сделкой.
# Использование: python xcheck_london.py <tester> <registry/configs/london_trap_XXX_M5.json> [папка BAZA]
import sys, os, json, csv, subprocess, tempfile, bisect
import xcheck_common as X

tester, cfg_path = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
cfg = json.load(open(cfg_path, encoding='utf-8-sig'))
if len(sys.argv) > 3: cfg['data']['bars_dir'] = sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__))
reg = json.load(open(os.path.join(here, '..', 'rules_registry.json'), encoding='utf-8-sig'))
rule = next(r for r in reg['rules'] if r['id'] == 'LONDON_TRAP_01')
P = {k: v['default'] for k, v in rule['params'].items()}
P.update(cfg['rules']['LONDON_TRAP_01'].get('params', {}))
pair, bdir = cfg['data']['pair'], cfg['data']['bars_dir']

with tempfile.TemporaryDirectory(dir=here) as tmp:      # папка проекта: путь без нелатинских букв
    cfg['output'] = os.path.join(tmp, 'res.json'); cfg['registry'] = os.path.join(here, '..', 'rules_registry.json')
    c2 = os.path.join(tmp, 'cfg.json'); json.dump(cfg, open(c2, 'w', encoding='utf-8'))
    tcsv = os.path.join(tmp, 'trades.csv')
    r = subprocess.run([tester, c2, '--trades=' + tcsv], capture_output=True)
    if r.returncode: print(r.stderr.decode('utf-8', 'replace')); sys.exit(2)
    res = json.load(open(cfg['output'], encoding='utf-8'))
    theirs = list(csv.DictReader(open(tcsv)))

path = lambda tf: os.path.join(bdir, pair, f'{pair}_{tf}.bin')
M, H, D = X.load(path('M5'), X.DEV_CUT), X.load(path('H1'), X.DEV_CUT), X.load(path('D1'), X.DEV_CUT)
T, O, Hi, Lo, C, SP, pt = M['T'], M['O'], M['H'], M['L'], M['C'], M['SP'], M['pt']; n = len(T)

def atr(B, p):
    h, l, c = B['H'], B['L'], B['C']; tr = []
    for i in range(len(c)):
        v = h[i] - l[i]
        if i: v = max(v, abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        tr.append(v)
    acc = [0.0]
    for v in tr: acc.append(acc[-1] + v)
    return [None if i + 1 < p else (acc[i + 1] - acc[i + 1 - p]) / p for i in range(len(c))]

A5, AD = atr(M, P['atr_period']), atr(D, P['atr_period'])

# --- направление H1 после каждой свечи ---
N = P['fractal_n']; hh, hl, hc = H['H'], H['L'], H['C']; bias_after = []; highs = []; lows = []; last = 0
for i in range(len(hc)):
    k = i - N
    if k >= N:
        near = list(range(k - N, k)) + list(range(k + 1, k + N + 1))
        if hh[k] > max(hh[j] for j in near): highs.append(hh[k])
        if hl[k] < min(hl[j] for j in near): lows.append(hl[k])
    up = bool(highs) and hc[i] > highs[-1]; dn = bool(lows) and hc[i] < lows[-1]
    if up or dn: last = 0 if (up and dn) else (1 if up else -1)
    b = 0
    if last == 1 and len(lows) > 1 and lows[-1] > lows[-2]: b = 1
    if last == -1 and len(highs) > 1 and highs[-1] < highs[-2]: b = -1
    bias_after.append(b)
h_close = [t + 3600 for t in H['T']]
d_close = [t + 86400 for t in D['T']]

# --- дни и средний спред часа ---
days = {}
for i, t in enumerate(T): days.setdefault(t // 86400, []).append(i)
hour_hist = {u: [] for u in range(24)}      # по часу: список (день, средний набор спредов дня)
for d in sorted(days):
    acc = {}
    for i in days[d]:
        u = T[i] % 86400 // 3600; s, c = acc.get(u, (0, 0)); acc[u] = (s + SP[i], c + 1)
    for u, sc in acc.items(): hour_hist[u].append((d, sc))
hour_days = {u: [d for d, _ in v] for u, v in hour_hist.items()}

def usual_spread(d, u):
    k = bisect.bisect_left(hour_days[u], d)
    prev = hour_hist[u][max(0, k - P['spread_days']):k]
    if not prev: return None
    return sum(s for _, (s, _) in prev) / sum(c for _, (_, c) in prev)

start_t = X.dev_windows(T[0])[0][1]; first = bisect.bisect_left(T, start_t)

# --- возможные входы: зависят только от цены ---
cands = []
for d in sorted(days):
    asia = [i for i in days[d] if T[i] % 86400 < P['asia_end_min'] * 60]
    win = [i for i in days[d] if P['asia_end_min'] * 60 <= T[i] % 86400 < P['window_end_min'] * 60]
    if len(asia) < P['min_asia_bars'] or not win: continue
    kd = bisect.bisect_right(d_close, d * 86400) - 1
    if kd < 0 or AD[kd] is None: continue
    top = max(Hi[i] for i in asia); bot = min(Lo[i] for i in asia)
    if not (top > bot and top - bot <= P['asia_atr_max'] * AD[kd] + 1e-12): continue
    kh = bisect.bisect_right(h_close, d * 86400 + P['asia_end_min'] * 60) - 1
    side = bias_after[kh] if kh >= 0 else 0
    if not side: continue
    # знак: приводим к случаю покупки (для продажи цены зеркалятся)
    low = (lambda i: Lo[i]) if side == 1 else (lambda i: -Hi[i])
    close = (lambda i: C[i]) if side == 1 else (lambda i: -C[i])
    edge = bot if side == 1 else -top
    p = 0
    while p < len(win):
        i = win[p]
        if low(i) >= edge or i == 0 or not A5[i - 1]: p += 1; continue
        a = A5[i - 1]; q = p; outside = 0; deepest = low(i); verdict = None
        while q < len(win):
            j = win[q]; deepest = min(deepest, low(j)); inside = close(j) > edge
            outside += 0 if inside else 1
            if edge - deepest > P['sweep_max_atr'] * a + 1e-12 or outside > P['max_outside']: verdict = 'move'; break
            if inside: verdict = 'back'; break
            q += 1
        if verdict != 'back': break          # истинное движение или окно кончилось
        j = win[q]
        if edge - deepest >= P['sweep_min_atr'] * a - 1e-12 and j >= first - 1:
            cands.append(dict(i=j, d=d, dir=side, ext=deepest * side, atr=a, top=top, bot=bot))
        p = q + 1

# --- сделки ---
lot = 100000; trades = []; busy_until = -1; stats = dict(rej_spread=0, rej_busy=0, rej_gap=0, rej_losses=0, rej_rr=0)
for s in cands:
    j, side = s['i'], s['dir']; counted = j >= first - 1
    usual = usual_spread(s['d'], T[j] % 86400 // 3600)
    if usual is None or SP[j] > P['spread_mult'] * usual + 1e-12: stats['rej_spread'] += 1; continue
    if j < busy_until: stats['rej_busy'] += 1; continue
    e = j + 1
    if e >= n: continue
    if T[e] - (T[j] + 300) > P['max_entry_gap_min'] * 60: stats['rej_gap'] += 1; continue
    day_e = T[e] // 86400
    if sum(1 for t in trades if t['pnl'] < 0 and T[t['out']] // 86400 == day_e) >= P['max_losses']: stats['rej_losses'] += 1; continue
    ask = lambda v, k: v + SP[k] * pt
    entry = ask(O[e], e) if side == 1 else O[e]
    pad = SP[j] * pt + P['sl_buffer_atr'] * s['atr']
    sl = s['ext'] - side * pad; tp = s['top'] if side == 1 else s['bot']
    risk = side * (entry - sl); gain = side * (tp - entry)
    if not (risk > 0 and gain > 0 and gain / risk >= P['min_rr'] - 1e-9): stats['rej_rr'] += 1; continue
    half = entry + P['be_fraction'] * (tp - entry); be_price = entry + side * SP[e] * pt
    stop = sl; moved = False; out = None
    for k in range(e, n):
        o, h, l = (O[k], Hi[k], Lo[k]) if side == 1 else (ask(O[k], k), ask(Hi[k], k), ask(Lo[k], k))
        worst, best = (l, h) if side == 1 else (h, l)
        if k > e and side * (o - stop) <= 0: out = (k, o, 'BE' if moved else 'SL'); break
        if side * (worst - stop) <= 0: out = (k, stop, 'BE' if moved else 'SL'); break
        if side * (best - tp) >= 0: out = (k, tp, 'TP'); break
        if not moved and side * (best - half) >= 0: moved = True; stop = be_price
    if out is None: k = n - 1; out = (k, C[k] if side == 1 else ask(C[k], k), 'END')
    k, px, why = out
    comm = 7 / lot * (1 if pair.endswith('USD') else entry)
    trades.append(dict(sig=j, e=e, out=k, dir=side, entry=entry, exit=px, sl=sl, tp=tp, pnl=side * (px - entry) - comm, why=why, be=int(moved)))
    busy_until = k
    if out[2] == 'END': busy_until = n

bad = 0
if len(trades) != len(theirs): bad += 1; print(f'ОШИБКА: сделок Python {len(trades)}, тестер {len(theirs)}')
mine = {T[t['e']]: t for t in trades}; other = {int(t['entry_time']): t for t in theirs}
only_m, only_t = sorted(set(mine) - set(other)), sorted(set(other) - set(mine))
if only_m or only_t: bad += 1; print('ОШИБКА: входы только в Python', only_m[:5], '; только в тестере', only_t[:5])
diff = 0
for key in sorted(set(mine) & set(other)):
    a, b = mine[key], other[key]
    ok = (T[a['sig']] == int(b['signal_time']) and T[a['out']] == int(b['exit_time']) and a['dir'] == int(b['dir'])
          and a['why'] == b['why'] and a['be'] == int(b['be'])
          and all(abs(a[f] - float(b[f])) < 1e-6 * max(1, abs(a[f]) * 1e-1) for f in ('entry', 'exit', 'sl', 'tp', 'pnl')))
    if not ok:
        diff += 1
        if diff <= 5: print('ОШИБКА сделка', key, a, b)
bad += diff > 0
f = res['rules'][0]['funnel']
for k, v in stats.items():
    if f[k] != v: bad += 1; print(f'ОШИБКА: {k}: Python {v}, тестер {f[k]}')
print(f"{'OK ' if not diff else 'ОШИБКА'} {pair}: сделок сверено {len(set(mine) & set(other))}, расхождений {diff}")
seen = [(T[t['e']], t['pnl'] / (10 * pt)) for t in trades]
bad += X.compare(res, seen, T[0])
sys.exit(1 if bad else 0)
