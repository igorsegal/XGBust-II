# Уровни H1 (ордер-блоки, равные экстремумы), направление, ATR и средний спред часа для независимых проверок. Код отдельный от C++.
import bisect

def atr(B, p):
    h, l, c = B['H'], B['L'], B['C']
    tr = [h[0] - l[0]] + [max(h[i], c[i - 1]) - min(l[i], c[i - 1]) for i in range(1, len(c))]
    acc = [0.0]
    for v in tr: acc.append(acc[-1] + v)
    return [None if i + 1 < p else (acc[i + 1] - acc[i + 1 - p]) / p for i in range(len(c))]

def structure(B, P):
    """Все уровни таймфрейма (номер свечи появления, нижняя, верхняя граница) и направление после каждой свечи."""
    o, h, l, c, sp = B['O'], B['H'], B['L'], B['C'], B['SP']; N = P['fractal_n']; m = len(c)
    swing_hi = {k for k in range(N, m - N) if h[k] > max(h[k - N:k]) and h[k] > max(h[k + 1:k + N + 1])}
    swing_lo = {k for k in range(N, m - N) if l[k] < min(l[k - N:k]) and l[k] < min(l[k + 1:k + N + 1])}
    out = dict(ob_buy=[], ob_sell=[], eq_low=[], eq_high=[]); bias = []; hs = []; ls = []; used_h = used_l = False; state = 0
    lb = lu = -1
    for i in range(m):
        bear, bull = lb, lu                                   # последняя свеча нужного цвета строго до i
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
            used_h = True
            if bear >= 0 and any(l[j + 1] > h[j - 1] for j in range(bear + 1, i)): out['ob_buy'].append((i, l[bear], h[bear]))
        if dn and not used_l:
            used_l = True
            if bull >= 0 and any(h[j + 1] < l[j - 1] for j in range(bull + 1, i)): out['ob_sell'].append((i, l[bull], h[bull]))
        b = 0
        if state == 1 and len(ls) > 1 and ls[-1] > ls[-2]: b = 1
        if state == -1 and len(hs) > 1 and hs[-1] < hs[-2]: b = -1
        bias.append(b)
    return out, bias

class H1Levels:
    def __init__(self, H, M, P):
        zones, self._bias = structure(H, P)
        self.close = [t + 3600 for t in H['T']]
        T, Lo, Hi = M['T'], M['L'], M['H']; n = len(T); BL = 512
        lo_blk = [min(Lo[i:i + BL]) for i in range(0, n, BL)]; hi_blk = [max(Hi[i:i + BL]) for i in range(0, n, BL)]
        def first_hit(i, arr, blk, test):
            while i < n:
                if i % BL == 0 and not test(blk[i // BL]): i += BL; continue
                if test(arr[i]): return i
                i += 1
            return n
        def death(kind, s, lo, hi):          # первая свеча M5, задевшая уровень
            if kind == 'ob_buy': return first_hit(s, Lo, lo_blk, lambda v: v <= hi)
            if kind == 'ob_sell': return first_hit(s, Hi, hi_blk, lambda v: v >= lo)
            if kind == 'eq_low': return first_hit(s, Lo, lo_blk, lambda v: v < lo)
            return first_hit(s, Hi, hi_blk, lambda v: v > hi)
        self.lv = {k: [(self.close[c], death(k, bisect.bisect_left(T, self.close[c]), lo, hi), lo, hi) for c, lo, hi in v] for k, v in zones.items()}

    def bias(self, now):
        k = bisect.bisect_right(self.close, now) - 1
        return self._bias[k] if k >= 0 else 0

    def target(self, side, price, now, idx):
        """Ближайший уровень H1, появившийся не позже now и не тронутый свечами M5 до idx (не включая)."""
        vals = []
        if side == 1:
            for k in ('ob_sell', 'eq_high'): vals += [lo for born, d, lo, hi in self.lv[k] if born <= now and d >= idx and lo > price]
            return min(vals) if vals else None
        for k in ('ob_buy', 'eq_low'): vals += [hi for born, d, lo, hi in self.lv[k] if born <= now and d >= idx and hi < price]
        return max(vals) if vals else None

class HourSpread:
    def __init__(self, T, SP, days):
        self.days = days; acc = {}
        for t, s in zip(T, SP):
            key = (t % 86400 // 3600, t // 86400); a = acc.get(key, (0, 0)); acc[key] = (a[0] + s, a[1] + 1)
        self.hist = {u: [] for u in range(24)}
        for (u, d), v in sorted(acc.items()): self.hist[u].append((d, v))
        self.keys = {u: [d for d, _ in v] for u, v in self.hist.items()}
    def usual(self, d, u):
        k = bisect.bisect_left(self.keys[u], d); prev = self.hist[u][max(0, k - self.days):k]
        return None if not prev else sum(s for _, (s, _) in prev) / sum(c for _, (_, c) in prev)
