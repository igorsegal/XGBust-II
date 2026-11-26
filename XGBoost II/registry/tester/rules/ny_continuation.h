// ny_continuation.h - NY_CONTINUATION_01 «Продолжение в Нью-Йорк»: лондонская коробка, неглубокий откат, пробой экстремума отката.
// Правила и допущения: registry/specs/NY_CONTINUATION_01.md. Всё считается по закрытым свечам.
#pragma once
#include "classic_trace.h"

struct NyFunnel { long days = 0, bias = 0, impulse = 0, pullback = 0, too_deep = 0, signals = 0, rej_spread = 0, rej_busy = 0, rej_losses = 0,
                       rej_gap = 0, rej_target = 0, rej_rr = 0, entries = 0; };
struct NyResult { std::vector<LtTrade> trades; std::vector<int> sigs; NyFunnel f; };

inline NyResult ny_run(const Params& P, const Bars& m, const Bars& h, int start_idx, double comm, bool by_price) {
    auto par = [&](const char* k) { auto it = P.find(k); if (it == P.end()) throw std::runtime_error(std::string("NY_CONTINUATION_01: нет параметра ") + k); return it->second; };
    const int N = (int)par("fractal_n"), boxStart = (int)par("box_start_min") * 60, boxEnd = (int)par("box_end_min") * 60, pullEnd = (int)par("pullback_end_min") * 60,
              entryEnd = (int)par("entry_end_min") * 60, minBox = (int)par("min_box_bars"), atrP = (int)par("atr_period"), spreadDays = (int)par("spread_days"), maxLoss = (int)par("max_losses");
    const double zMin = par("retrace_min"), zMax = par("retrace_max"), zClose = par("retrace_close_max"), buf = par("sl_buffer_atr"), minRR = par("min_rr"),
                 beFr = par("be_fraction"), eqM = par("eq_spread_mult"), spMult = par("spread_mult"), maxGap = par("max_entry_gap_min") * 60;
    if (m.period_sec != 300 || h.period_sec != 3600) throw std::runtime_error("NY_CONTINUATION_01 работает на M5 с направлением по H1");

    const int n = (int)m.size(); const double pt = m.point;
    NyResult R; R.sigs.assign(n, 0);
    const std::vector<double> A = lt_atr(m, atrP);
    CtStruct S1(h, N, eqM); size_t hi = 0;
    auto feed_h1 = [&](int64_t now) { while (hi < h.size() && h.t[hi] + h.period_sec <= now) S1.feed(hi++); };
    struct HourAcc { std::vector<std::pair<double, long>> days; double s = 0; long c = 0; };
    HourAcc H[24];

    int64_t day = -1; int losses = 0;
    std::vector<int> box; bool built = false, live = false, zoneChecked = false, zoneOk = false, traded = false;
    int dir = 0, peak = -1; double top = 0, height = 0, pullExt = 0; bool pullAny = false;
    // последние свинги M5 и признак, что уровень уже пробит
    int shK = -1, slK = -1; double shV = 0, slV = 0; bool shDone = false, slDone = false;
    bool pend = false; int o_sig = 0, o_dir = 0; double o_sl = 0;
    bool pos = false; LtTrade T{}; double stop = 0, beTrig = 0, spIn = 0; bool beArmed = false;

    auto close_pos = [&](int i, double px, const char* why) {
        T.i_out = i; T.exit = px; T.why = why;
        T.pnl = (T.dir > 0 ? px - T.entry : T.entry - px) - comm * (by_price ? T.entry : 1.0);
        T.R = T.pnl / std::fabs(T.entry - T.sl);
        if (T.pnl < 0) ++losses;
        R.trades.push_back(T); pos = false;
    };

    for (int i = 0; i < n; ++i) {
        const int64_t t = m.t[i], dd = t / 86400, sec = t % 86400;
        const bool inTest = i >= start_idx;
        if (dd != day) {
            if (day >= 0) for (int u = 0; u < 24; ++u) { if (!H[u].c) continue; H[u].days.push_back({H[u].s, H[u].c}); if ((int)H[u].days.size() > spreadDays) H[u].days.erase(H[u].days.begin()); H[u].s = 0; H[u].c = 0; }
            day = dd; losses = 0; box.clear(); built = false; live = false; zoneChecked = false; zoneOk = false; traded = false; pullAny = false;
        }
        const double sp = m.spread[i] * pt;

        // коробка строится на первой свече с 12:00; направление - по H1, закрытым ровно к 12:00
        if (!built && sec >= boxEnd) {
            built = true;
            if ((int)box.size() >= minBox) {
                feed_h1(dd * 86400 + boxEnd); const int bs = S1.bias();
                if (inTest) { ++R.f.days; if (bs) ++R.f.bias; }
                if (bs) {
                    int iHi = box[0], iLo = box[0];
                    for (int k : box) { if (m.h[k] > m.h[iHi]) iHi = k; if (m.l[k] < m.l[iLo]) iLo = k; }
                    if (bs > 0 ? iLo < iHi : iHi < iLo) {
                        live = true; dir = bs; peak = bs > 0 ? iHi : iLo; top = bs > 0 ? m.h[iHi] : m.l[iLo]; height = m.h[iHi] - m.l[iLo];
                        if (height <= 0) live = false; else if (inTest) ++R.f.impulse;
                    }
                }
            }
        }
        feed_h1(t);

        // 1. вход по открытию этой свечи
        if (pend) {
            pend = false;
            if (t - (m.t[o_sig] + m.period_sec) > (int64_t)maxGap) { if (inTest) ++R.f.rej_gap; }
            else if (losses >= maxLoss) { if (inTest) ++R.f.rej_losses; }
            else {
                const double entry = o_dir > 0 ? m.o[i] + sp : m.o[i];
                const double tp = S1.target(o_dir, entry);
                if (std::isnan(tp)) { if (inTest) ++R.f.rej_target; }
                else {
                    const double risk = o_dir > 0 ? entry - o_sl : o_sl - entry, reward = o_dir > 0 ? tp - entry : entry - tp;
                    if (!(risk > 0 && reward > 0 && reward / risk >= minRR - 1e-9)) { if (inTest) ++R.f.rej_rr; }
                    else {
                        pos = true; T = LtTrade{o_sig, i, -1, o_dir, entry, 0, o_sl, tp, 0, 0, 0, ""}; traded = true;
                        stop = o_sl; spIn = sp; beArmed = false; beTrig = entry + beFr * (tp - entry); if (inTest) ++R.f.entries;
                    }
                }
            }
        }

        // 2. позиция на этой свече
        if (pos) {
            const char* lbl = beArmed ? "BE" : "SL";
            if (T.dir > 0) {
                if (i > T.i_in && m.o[i] <= stop) close_pos(i, m.o[i], lbl);
                else if (m.l[i] <= stop) close_pos(i, stop, lbl);
                else if (m.h[i] >= T.tp) close_pos(i, T.tp, "TP");
                else if (!beArmed && m.h[i] >= beTrig) { beArmed = true; T.be = 1; stop = T.entry + spIn; }
            } else {
                const double ao = m.o[i] + sp, ah = m.h[i] + sp, al = m.l[i] + sp;
                if (i > T.i_in && ao >= stop) close_pos(i, ao, lbl);
                else if (ah >= stop) close_pos(i, stop, lbl);
                else if (al <= T.tp) close_pos(i, T.tp, "TP");
                else if (!beArmed && al <= beTrig) { beArmed = true; T.be = 1; stop = T.entry - spIn; }
            }
        }
        const int hour = (int)(sec / 3600);
        H[hour].s += m.spread[i]; H[hour].c++;

        // 3. свеча закрылась: уровни H1, свинги M5, пробой
        S1.touch(m.l[i], m.h[i]);
        feed_h1(t + m.period_sec);
        if (i >= 2 * N) {
            const int k = i - N; bool isH = true, isL = true;
            for (int j = 1; j <= N; ++j) {
                if (!(m.h[k] > m.h[k - j] && m.h[k] > m.h[k + j])) isH = false;
                if (!(m.l[k] < m.l[k - j] && m.l[k] < m.l[k + j])) isL = false;
            }
            if (isH) { shK = k; shV = m.h[k]; shDone = false; }
            if (isL) { slK = k; slV = m.l[k]; slDone = false; }
        }
        const bool brokeUp = shK >= 0 && !shDone && m.c[i] > shV, brokeDn = slK >= 0 && !slDone && m.c[i] < slV;
        if (brokeUp) shDone = true;
        if (brokeDn) slDone = true;

        if (sec >= boxStart && sec < boxEnd) { box.push_back(i); continue; }
        if (!live || sec < boxEnd) continue;

        // 4. откат
        if (sec < pullEnd) {
            const double v = dir > 0 ? m.l[i] : m.h[i];
            if (!pullAny || (dir > 0 ? v < pullExt : v > pullExt)) { pullExt = v; pullAny = true; }
        } else if (!zoneChecked) {
            zoneChecked = true;
            if (pullAny) { const double depth = dir > 0 ? top - pullExt : pullExt - top; zoneOk = depth >= zMin * height - 1e-9 * pt && depth <= zMax * height + 1e-9 * pt; }
            if (zoneOk && inTest) ++R.f.pullback;
        }
        if (sec < entryEnd && !traded && (dir > 0 ? m.c[i] < top - zClose * height - 1e-9 * pt : m.c[i] > top + zClose * height + 1e-9 * pt)) { live = false; if (inTest) ++R.f.too_deep; continue; }

        // 5. сигнал
        if (sec < pullEnd || sec >= entryEnd || !zoneOk || traded) continue;
        const bool broke = dir > 0 ? brokeUp : brokeDn; const int k = dir > 0 ? shK : slK; const double lvl = dir > 0 ? shV : slV;
        if (!broke || k <= peak || !(dir > 0 ? lvl < top : lvl > top)) continue;
        if (i < start_idx - 1 || std::isnan(A[i])) continue;
        R.sigs[i] = dir; if (inTest) ++R.f.signals;
        double s = 0; long c = 0; for (const auto& q : H[hour].days) { s += q.first; c += q.second; }
        if (!c || m.spread[i] > spMult * (s / c) + 1e-12) { if (inTest) ++R.f.rej_spread; continue; }
        if (pos) { if (inTest) ++R.f.rej_busy; continue; }
        if (losses >= maxLoss) { if (inTest) ++R.f.rej_losses; continue; }
        if (i + 1 >= n) continue;
        double ext = dir > 0 ? m.l[peak + 1] : m.h[peak + 1];
        for (int j = peak + 1; j <= i; ++j) ext = dir > 0 ? std::min(ext, m.l[j]) : std::max(ext, m.h[j]);
        pend = true; o_sig = i; o_dir = dir; o_sl = dir > 0 ? ext - (sp + buf * A[i]) : ext + (sp + buf * A[i]);
    }
    if (pos) close_pos(n - 1, T.dir > 0 ? m.c[n - 1] : m.c[n - 1] + m.spread[n - 1] * pt, "END");
    return R;
}
