// london_trap.h - LONDON_TRAP_01 «Лондонский капкан»: стратегия со своими входом, стопом, целью и безубытком.
// Правила и допущения: registry/specs/LONDON_TRAP_01.md. Всё считается по закрытым свечам.
#pragma once
#include "../bars.h"
#include <algorithm>

struct LtTrade { int i_sig, i_in, i_out; int dir; double entry, exit, sl, tp, pnl, R; int be; std::string why; };
struct LtFunnel {   // счётчики по дням и сигналам, вошедшим в проверочный отрезок
    long days = 0, bias = 0, asia_ok = 0, ready = 0, swept = 0, true_move = 0, returns = 0,
         rej_spread = 0, rej_busy = 0, rej_gap = 0, rej_losses = 0, rej_rr = 0, entries = 0;
};
struct LtResult { std::vector<LtTrade> trades; std::vector<int> sigs; LtFunnel f; };

// ATR: простое среднее истинного диапазона за p свечей, значение на свече i включает свечу i
inline std::vector<double> lt_atr(const Bars& b, int p) {
    size_t n = b.size(); std::vector<double> tr(n), a(n, NAN); double s = 0;
    for (size_t i = 0; i < n; ++i) {
        double r = b.h[i] - b.l[i];
        if (i) r = std::max(r, std::max(std::fabs(b.h[i] - b.c[i - 1]), std::fabs(b.l[i] - b.c[i - 1])));
        tr[i] = r; s += r; if (i >= (size_t)p) s -= tr[i - p]; if (i + 1 >= (size_t)p) a[i] = s / p;
    }
    return a;
}

// start_idx: с этой свечи разрешены сигналы; comm - комиссия на единицу лота в долларах; by_price - котировка не в долларах
inline LtResult lt_run(const Params& P, const Bars& m, const Bars& h, const Bars& d, int start_idx, double comm, bool by_price) {
    auto par = [&](const char* k) { auto it = P.find(k); if (it == P.end()) throw std::runtime_error(std::string("LONDON_TRAP_01: нет параметра ") + k); return it->second; };
    const int N = (int)par("fractal_n"), asiaEnd = (int)par("asia_end_min") * 60, winEnd = (int)par("window_end_min") * 60;
    const int atrP = (int)par("atr_period"), maxOut = (int)par("max_outside"), spreadDays = (int)par("spread_days"), maxLoss = (int)par("max_losses"), minAsia = (int)par("min_asia_bars");
    const double asiaMax = par("asia_atr_max"), swMin = par("sweep_min_atr"), swMax = par("sweep_max_atr"), buf = par("sl_buffer_atr"),
                 minRR = par("min_rr"), beFr = par("be_fraction"), spMult = par("spread_mult"), maxGap = par("max_entry_gap_min") * 60;
    if (m.period_sec != 300 || h.period_sec != 3600 || d.period_sec != 86400) throw std::runtime_error("LONDON_TRAP_01 работает на M5 с направлением по H1 и дневными свечами");

    const int n = (int)m.size(); const double pt = m.point;
    LtResult R; R.sigs.assign(n, 0);
    std::vector<double> A = lt_atr(m, atrP), AD = lt_atr(d, atrP);

    // направление по H1
    size_t hi = 0; double sh[2] = {NAN, NAN}, sl_[2] = {NAN, NAN}; int lastBreak = 0;    // [0] - последний свинг, [1] - предыдущий
    auto feed_h1 = [&](int64_t now) {
        while (hi < h.size() && h.t[hi] + h.period_sec <= now) {
            if ((int)hi >= 2 * N) {
                size_t k = hi - N; bool isH = true, isL = true;
                for (int j = 1; j <= N; ++j) {
                    if (!(h.h[k] > h.h[k - j] && h.h[k] > h.h[k + j])) isH = false;
                    if (!(h.l[k] < h.l[k - j] && h.l[k] < h.l[k + j])) isL = false;
                }
                if (isH) { sh[1] = sh[0]; sh[0] = h.h[k]; }
                if (isL) { sl_[1] = sl_[0]; sl_[0] = h.l[k]; }
            }
            bool up = !std::isnan(sh[0]) && h.c[hi] > sh[0], dn = !std::isnan(sl_[0]) && h.c[hi] < sl_[0];
            if (up && dn) lastBreak = 0; else if (up) lastBreak = 1; else if (dn) lastBreak = -1;
            ++hi;
        }
    };
    auto bias_now = [&]() {
        if (lastBreak > 0 && !std::isnan(sl_[1]) && sl_[0] > sl_[1]) return 1;
        if (lastBreak < 0 && !std::isnan(sh[1]) && sh[0] < sh[1]) return -1;
        return 0;
    };

    // средний спред часа за предыдущие дни: по каждому часу очередь дневных сумм
    struct HourAcc { std::vector<std::pair<double, long>> days; double s = 0; long c = 0; };
    HourAcc H[24];
    auto close_day_spreads = [&]() {
        for (int u = 0; u < 24; ++u) { if (!H[u].c) continue; H[u].days.push_back({H[u].s, H[u].c}); if ((int)H[u].days.size() > spreadDays) H[u].days.erase(H[u].days.begin()); H[u].s = 0; H[u].c = 0; }
    };

    size_t di = 0; double atrD = NAN;
    int64_t day = -1; int bias = 0; bool biasSet = false, dayOff = false, counted = false, inEx = false, sweptToday = false;
    double aHi = 0, aLo = 0; int aN = 0; bool asiaOk = false;
    int outside = 0; double ext = 0, exAtr = 0;
    bool pend = false; int p_sig = 0, p_dir = 0; double p_sl = 0, p_tp = 0;
    bool pos = false; LtTrade T{}; double stop = 0, beTrig = 0, spIn = 0; bool beArmed = false; int losses = 0;

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
            if (day >= 0) close_day_spreads();
            day = dd; bias = 0; biasSet = false; dayOff = false; counted = false; inEx = false; sweptToday = false; aN = 0; asiaOk = false; losses = 0;
            while (di < d.size() && d.t[di] + d.period_sec <= dd * 86400) ++di;
            atrD = di ? AD[di - 1] : NAN;
        }
        const double sp = m.spread[i] * pt;

        // 1. отложенный вход: по открытию этой свечи
        if (pend) {
            pend = false;
            if (t - (m.t[p_sig] + m.period_sec) > (int64_t)maxGap) { if (inTest) ++R.f.rej_gap; }
            else if (losses >= maxLoss) { if (inTest) ++R.f.rej_losses; }
            else {
                double entry = p_dir > 0 ? m.o[i] + sp : m.o[i];
                double risk = p_dir > 0 ? entry - p_sl : p_sl - entry, reward = p_dir > 0 ? p_tp - entry : entry - p_tp;
                if (!(risk > 0 && reward > 0 && reward / risk >= minRR - 1e-9)) { if (inTest) ++R.f.rej_rr; }
                else {
                    pos = true; T = LtTrade{p_sig, i, -1, p_dir, entry, 0, p_sl, p_tp, 0, 0, 0, ""};
                    stop = p_sl; spIn = sp; beArmed = false; beTrig = entry + beFr * (p_tp - entry); if (inTest) ++R.f.entries;
                }
            }
        }

        // 2. ведение позиции на этой свече
        if (pos) {
            const char* lbl = beArmed ? "BE" : "SL";
            if (T.dir > 0) {
                if (i > T.i_in && m.o[i] <= stop) close_pos(i, m.o[i], lbl);
                else if (m.l[i] <= stop) close_pos(i, stop, lbl);
                else if (m.h[i] >= T.tp) close_pos(i, T.tp, "TP");
                else if (!beArmed && m.h[i] >= beTrig) { beArmed = true; T.be = 1; stop = T.entry + spIn; }
            } else {
                double ao = m.o[i] + sp, ah = m.h[i] + sp, al = m.l[i] + sp;
                if (i > T.i_in && ao >= stop) close_pos(i, ao, lbl);
                else if (ah >= stop) close_pos(i, stop, lbl);
                else if (al <= T.tp) close_pos(i, T.tp, "TP");
                else if (!beArmed && al <= beTrig) { beArmed = true; T.be = 1; stop = T.entry - spIn; }
            }
        }

        // средний спред копится по всем свечам; сравнение идёт только с прошлыми днями
        const int hour = (int)(sec / 3600);
        H[hour].s += m.spread[i]; H[hour].c++;

        // 3. правила на закрытии свечи
        if (sec < asiaEnd) {
            if (!aN) { aHi = m.h[i]; aLo = m.l[i]; } else { aHi = std::max(aHi, m.h[i]); aLo = std::min(aLo, m.l[i]); }
            ++aN; continue;
        }
        if (sec >= winEnd) continue;
        if (!biasSet) { feed_h1(dd * 86400 + asiaEnd); bias = bias_now(); biasSet = true; }
        if (!counted) {
            counted = true;
            asiaOk = aN >= minAsia && !std::isnan(atrD) && aHi > aLo && aHi - aLo <= asiaMax * atrD + 1e-12;
            if (inTest && aN) { ++R.f.days; if (bias) ++R.f.bias; if (asiaOk) ++R.f.asia_ok; if (bias && asiaOk) ++R.f.ready; }
        }
        if (!bias || !asiaOk || dayOff) continue;

        const double edge = bias > 0 ? aLo : aHi;
        const bool beyond = bias > 0 ? m.l[i] < edge : m.h[i] > edge;
        if (!inEx) {
            if (!beyond) continue;
            if (i == 0 || std::isnan(A[i - 1]) || A[i - 1] <= 0) continue;
            inEx = true; outside = 0; exAtr = A[i - 1]; ext = bias > 0 ? m.l[i] : m.h[i];
            if (!sweptToday) { sweptToday = true; if (inTest) ++R.f.swept; }
        }
        ext = bias > 0 ? std::min(ext, m.l[i]) : std::max(ext, m.h[i]);
        const double depth = bias > 0 ? edge - ext : ext - edge;
        const bool back = bias > 0 ? m.c[i] > edge : m.c[i] < edge;
        if (!back) ++outside;
        if (depth > swMax * exAtr + 1e-12 || outside > maxOut) { dayOff = true; inEx = false; if (inTest) ++R.f.true_move; continue; }
        if (!back) continue;
        inEx = false;
        if (depth < swMin * exAtr - 1e-12) continue;
        if (i < start_idx - 1) continue;
        // возврат подтверждён
        R.sigs[i] = bias; if (inTest) ++R.f.returns;
        double s = 0; long c = 0; for (const auto& q : H[hour].days) { s += q.first; c += q.second; }
        if (!c || m.spread[i] > spMult * (s / c) + 1e-12) { if (inTest) ++R.f.rej_spread; continue; }
        if (pos) { if (inTest) ++R.f.rej_busy; continue; }
        if (i + 1 >= n) continue;
        pend = true; p_sig = i; p_dir = bias;
        p_sl = bias > 0 ? ext - (sp + buf * exAtr) : ext + (sp + buf * exAtr);
        p_tp = bias > 0 ? aHi : aLo;
    }
    if (pos) close_pos(n - 1, T.dir > 0 ? m.c[n - 1] : m.c[n - 1] + m.spread[n - 1] * pt, "END");
    return R;
}
