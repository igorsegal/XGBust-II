# Независимая проверка NY_CONTINUATION_01: правило пересчитывается на Python по тексту registry/specs/NY_CONTINUATION_01.md
# (по дням: коробка, откат, пробои; уровни H1 строит общая функция проверки) и сравнивается с тестером сделка за сделкой.
# Использование: python xcheck_ny.py <tester> <registry/configs/ny_continuation_XXX_M5.json> [папка BAZA]
import sys, os, json, csv, subprocess, tempfile, bisect
import xcheck_common as X
import xcheck_levels as Lv

RID = 'NY_CONTINUATION_01'
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
A = Lv.atr(M, P['atr_period'])
H1 = Lv.H1Levels(H, M, P)
start_t = X.dev_windows(T[0])[0][1]; first = bisect.bisect_left(T, start_t)
F = {k: 0 for k in res['rules'][0]['funnel']}
def count(key, i):
    if i >= first: F[key] += 1

# --- свинги M5: номер свечи свинга и первая свеча после него с закрытием за уровнем ---
N = P['fractal_n']
def swings(side):
    v = Hi if side == 1 else [-x for x in Lo]
    c = C if side == 1 else [-x for x in C]
    out = []
    for k in range(N, n - N):
        if v[k] > max(v[k - N:k]) and v[k] > max(v[k + 1:k + N + 1]): out.append(k)
    return out, v, c
SW = {1: swings(1), -1: swings(-1)}

days = {}
for i, t in enumerate(T): days.setdefault(t // 86400, []).append(i)
sec = lambda i: T[i] % 86400
spread = Lv.HourSpread(T, SP, P['spread_days'])

# --- сигналы по дням (зависят только от цены) ---
daysig = []
for d in sorted(days):
    box = [i for i in days[d] if P['box_start_min'] * 60 <= sec(i) < P['box_end_min'] * 60]
    after = [i for i in days[d] if sec(i) >= P['box_end_min'] * 60]
    if len(box) < P['min_box_bars'] or not after: continue
    count('days', after[0])
    side = H1.bias(d * 86400 + P['box_end_min'] * 60)
    if not side: continue
    count('days_bias', after[0])
    hi_i = max(box, key=lambda i: (Hi[i], -i)); lo_i = min(box, key=lambda i: (Lo[i], i))
    start, peak = (lo_i, hi_i) if side == 1 else (hi_i, lo_i)
    height = Hi[hi_i] - Lo[lo_i]
    if not (start < peak and height > 0): continue
    count('days_impulse', after[0])
    top = Hi[peak] if side == 1 else Lo[peak]
    depth_of = lambda price: side * (top - price)
    pull = [i for i in after if sec(i) < P['pullback_end_min'] * 60]
    zone = False
    if pull:
        deepest = max(depth_of(Lo[i] if side == 1 else Hi[i]) for i in pull)
        zone = P['retrace_min'] * height - 1e-9 * pt <= deepest <= P['retrace_max'] * height + 1e-9 * pt
    # первая свеча с закрытием глубже 0,705 в пределах окна
    deep = next((i for i in after if sec(i) < P['entry_end_min'] * 60 and depth_of(C[i]) > P['retrace_close_max'] * height + 1e-9 * pt), None)
    list_, v, c = SW[side]
    breaks = []
    for i in after:
        if sec(i) >= P['entry_end_min'] * 60: break
        if sec(i) < P['pullback_end_min'] * 60: continue
        q = bisect.bisect_right(list_, i - N) - 1          # последний свинг, подтверждённый к закрытию свечи i
        if q < 0: continue
        k = list_[q]
        if k <= peak or not side * top > v[k]: continue
        if c[i] > v[k] and not any(c[j] > v[k] for j in range(k + 1, i)): breaks.append(i)
    late = next((i for i in after if sec(i) >= P['pullback_end_min'] * 60), None)
    daysig.append(dict(side=side, peak=peak, zone=zone, deep=deep, breaks=breaks, late=late))

# --- сделки ---
lot = 100000; trades = []; busy = -1
def losses_on(day): return sum(1 for t in trades if t['pnl'] < 0 and T[t['out']] // 86400 == day)
for s in daysig:
    side, peak, deep = s['side'], s['peak'], s['deep']
    traded_at = None
    if s['zone'] and s['late'] is not None and (deep is None or deep >= s['late']): count('days_pullback', s['late'])
    elif s['zone'] and s['late'] is not None and deep is not None: pass
    for j in s['breaks']:
        if not s['zone'] or (deep is not None and j >= deep) or traded_at is not None: continue
        if j < first - 1 or A[j] is None: continue
        count('signals', j)
        usual = spread.usual(T[j] // 86400, sec(j) // 3600)
        if usual is None or SP[j] > P['spread_mult'] * usual + 1e-12: count('rej_spread', j); continue
        if j < busy: count('rej_busy', j); continue
        if losses_on(T[j] // 86400) >= P['max_losses']: count('rej_losses', j); continue
        e = j + 1
        if e >= n: continue
        if T[e] - (T[j] + 300) > P['max_entry_gap_min'] * 60: count('rej_gap', e); continue
        if losses_on(T[e] // 86400) >= P['max_losses']: count('rej_losses', e); continue
        ext = min(Lo[peak + 1:j + 1]) if side == 1 else max(Hi[peak + 1:j + 1])
        sl = ext - side * (SP[j] * pt + P['sl_buffer_atr'] * A[j])
        entry = O[e] + SP[e] * pt if side == 1 else O[e]
        tp = H1.target(side, entry, T[e], e)
        if tp is None: count('rej_target', e); continue
        risk, gain = side * (entry - sl), side * (tp - entry)
        if not (risk > 0 and gain > 0 and gain / risk >= P['min_rr'] - 1e-9): count('rej_rr', e); continue
        count('entries', e); traded_at = e
        half = entry + P['be_fraction'] * (tp - entry); be_price = entry + side * SP[e] * pt; stop = sl; moved = False
        for k in range(e, n):
            add = 0 if side == 1 else SP[k] * pt
            o, worst, best = O[k] + add, (Lo[k] if side == 1 else Hi[k]) + add, (Hi[k] if side == 1 else Lo[k]) + add
            if k > e and side * (o - stop) <= 0: px, why = o, 'BE' if moved else 'SL'; break
            if side * (worst - stop) <= 0: px, why = stop, 'BE' if moved else 'SL'; break
            if side * (best - tp) >= 0: px, why = tp, 'TP'; break
            if not moved and side * (best - half) >= 0: moved = True; stop = be_price
        else:
            k = n - 1; px, why = (C[k] if side == 1 else C[k] + SP[k] * pt), 'END'
        comm = 7 / lot * (1 if pair.endswith('USD') else entry)
        trades.append(dict(sig=j, e=e, out=k, dir=side, entry=entry, exit=px, sl=sl, tp=tp, pnl=side * (px - entry) - comm, why=why, be=int(moved)))
        busy = n if why == 'END' else k
    # день отменён глубоким закрытием, если оно случилось до первой сделки
    if deep is not None and (traded_at is None or deep < traded_at): count('days_too_deep', deep)

bad = 0
if len(trades) != len(theirs): bad += 1; print(f'ОШИБКА: сделок Python {len(trades)}, тестер {len(theirs)}')
mine = {T[t['e']]: t for t in trades}; other = {int(t['entry_time']): t for t in theirs}
only_m, only_t = sorted(set(mine) - set(other)), sorted(set(other) - set(mine))
if only_m or only_t: bad += 1; print('ОШИБКА: входы только в Python', len(only_m), only_m[:5], '; только в тестере', len(only_t), only_t[:5])
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
for k, v in res['rules'][0]['funnel'].items():
    if F[k] != v: bad += 1; print(f'ОШИБКА: {k}: Python {F[k]}, тестер {v}')
print(f"{'OK ' if not diff else 'ОШИБКА'} {pair}: сделок сверено {len(set(mine) & set(other))}, расхождений {diff}")
bad += X.compare(res, [(T[t['e']], t['pnl'] / (10 * pt)) for t in trades], T[0])
sys.exit(1 if bad else 0)
