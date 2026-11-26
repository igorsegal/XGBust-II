#!/usr/bin/env python3
"""xcheck_expr_example.py - независимая проверка движка условий на правиле EXAMPLE_RSI_PULLBACK_01.
Сигналы и сделки считаются заново отдельным кодом на Python и сравниваются с результатом тестера по разработке и каждому окну.
Использование: python xcheck_expr_example.py <папка BAZA> <результат тестера .json> [rsi_period rsi_low rsi_high ema_period]"""
import sys, json, bisect, os
import xcheck_common as X

raw, resf = sys.argv[1], sys.argv[2]
rsi_p, lo, hi, ema_p = [float(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else (14, 30, 70, 50)
rsi_p, ema_p = int(rsi_p), int(ema_p)
res = json.load(open(resf, encoding='utf-8')); pair = res['pair']
B = X.load(os.path.join(raw, pair, pair + '_H1.bin'), X.DEV_CUT); B4 = X.load(os.path.join(raw, pair, pair + '_H4.bin'), X.DEV_CUT)
per, T, H, L, C = B['per'], B['T'], B['H'], B['L'], B['C']; per4, T4, C4 = B4['per'], B4['T'], B4['C']; n = len(C)
# RSI (Wilder)
rsi = [None] * n; ag = al = 0.0
for i in range(1, rsi_p + 1):
    d = C[i] - C[i - 1]; ag += max(d, 0); al += max(-d, 0)
ag /= rsi_p; al /= rsi_p; rsi[rsi_p] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
for i in range(rsi_p + 1, n):
    d = C[i] - C[i - 1]; ag = (ag * (rsi_p - 1) + max(d, 0)) / rsi_p; al = (al * (rsi_p - 1) + max(-d, 0)) / rsi_p
    rsi[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
# EMA на H4
ema4 = [None] * len(C4); k = 2 / (ema_p + 1); e = sum(C4[:ema_p]) / ema_p; ema4[ema_p - 1] = e
for j in range(ema_p, len(C4)):
    e = e + k * (C4[j] - e); ema4[j] = e
close4 = [T4[j] + per4 for j in range(len(C4))]           # момент закрытия каждого бара H4
sig = [0] * n
for i in range(n):
    j = bisect.bisect_right(close4, T[i] + per) - 1        # последний бар H4, закрытый к закрытию бара H1
    if j < 0 or ema4[j] is None or rsi[i] is None: continue
    l = rsi[i] < lo and C[i] > ema4[j]; s = rsi[i] > hi and C[i] < ema4[j]
    sig[i] = 0 if (l and s) else (1 if l else (-1 if s else 0))
sys.exit(X.compare(res, X.trades(B, sig, pair, X.dev_windows(T[0])[0][1]), T[0]))
