// classic_trace.h - CLASSIC_TRACE_01 «Классический след»: треугольник, вынос против направления H1 и возврат.
// Правила и допущения: registry/specs/CLASSIC_TRACE_01.md. Всё считается по закрытым свечам.
#pragma once
#include "london_trap.h"

struct CtZone { double lo, hi; };        // ордер-блок: границы свечи; скопление равных экстремумов: меньший и больший

// Свинги, слом структуры, ордер-блоки и равные экстремумы одного таймфрейма
struct CtStruct {
    const Bars& b; int N; double eqMult;
    double sh[2] = {NAN, NAN}, sl[2] = {NAN, NAN}; bool shBroken = false, slBroken = false; int lastBreak = 0;
    std::vector<CtZone> demand, supply, eqLow, eqHigh;
    CtStruct(const Bars& bars, int n, double m) : b(bars), N(n), eqMult(m) {}

    void feed(size_t i) {      // свеча i закрылась
        if ((int)i >= 2 * N) {
            size_t k = i - N; bool isH = true, isL = true;
            for (int j = 1; j <= N; ++j) {
                if (!(b.h[k] > b.h[k - j] && b.h[k] > b.h[k + j])) isH = false;
                if (!(b.l[k] < b.l[k - j] && b.l[k] < b.l[k + j])) isL = false;
            }
            const double tol = eqMult * b.spread[i] * b.point + 1e-9 * b.point;
            if (isH) { sh[1] = sh[0]; sh[0] = b.h[k]; shBroken = false;
                if (!std::isnan(sh[1]) && std::fabs(sh[0] - sh[1]) <= tol) eqHigh.push_back({std::min(sh[0], sh[1]), std::max(sh[0], sh[1])}); }
            if (isL) { sl[1] = sl[0]; sl[0] = b.l[k]; slBroken = false;
                if (!std::isnan(sl[1]) && std::fabs(sl[0] - sl[1]) <= tol) eqLow.push_back({std::min(sl[0], sl[1]), std::max(sl[0], sl[1])}); }
        }
        const bool up = !std::isnan(sh[0]) && b.c[i] > sh[0], dn = !std::isnan(sl[0]) && b.c[i] < sl[0];
        if (up && dn) lastBreak = 0; else if (up) lastBreak = 1; else if (dn) lastBreak = -1;
        if (up && !shBroken) { shBroken = true; order_block(i, 1); }
        if (dn && !slBroken) { slBroken = true; order_block(i, -1); }
    }
    void order_block(size_t k, int dir) {
        long o = (long)k - 1;
        while (o >= 0 && !(dir > 0 ? b.c[o] < b.o[o] : b.c[o] > b.o[o])) --o;
        if (o < 0) return;
        bool gap = false;
        for (long j = o + 1; j + 1 <= (long)k; ++j)
            if (dir > 0 ? b.l[j + 1] > b.h[j - 1] : b.h[j + 1] < b.l[j - 1]) { gap = true; break; }
        if (gap) (dir > 0 ? demand : supply).push_back({b.l[o], b.h[o]});
    }
    void touch(double low, double high) {      // цена прошла свечу: тронутые уровни убираются
        auto drop = [](std::vector<CtZone>& v, auto pred) { v.erase(std::remove_if(v.begin(), v.end(), pred), v.end()); };
        drop(demand, [&](const CtZone& z) { return low <= z.hi; });
        drop(supply, [&](const CtZone& z) { return high >= z.lo; });
        drop(eqLow, [&](const CtZone& z) { return low < z.lo; });
        drop(eqHigh, [&](const CtZone& z) { return high > z.hi; });
    }
    int bias() const {
        if (lastBreak > 0 && !std::isnan(sl[1]) && sl[0] > sl[1]) return 1;
        if (lastBreak < 0 && !std::isnan(sh[1]) && sh[0] < sh[1]) return -1;
        return 0;
    }
    // ближайший нетронутый уровень по направлению сделки дальше цены; NAN - нет
    double target(int dir, double price) const {
        double best = NAN;
        auto take = [&](double v) { if (dir > 0 ? v > price : v < price) if (std::isnan(best) || (dir > 0 ? v < best : v > best)) best = v; };
        if (dir > 0) { for (const auto& z : supply) take(z.lo); for (const auto& z : eqHigh) take(z.lo); }
        else { for (const auto& z : demand) take(z.hi); for (const auto& z : eqLow) take(z.hi); }
        return best;
    }
};

struct CtFunnel { long breakouts = 0, true_moves = 0, returns = 0, rej_spread = 0, rej_busy = 0, rej_losses = 0, landmark = 0,
                       rej_gap = 0, rej_target = 0, rej_rr = 0, limit_placed = 0, limit_dropped = 0, entries_market = 0, entries_limit = 0; };
struct CtResult { std::vector<LtTrade> trades; std::vector<int> sigs; std::vector<int> lim; CtFunnel f; };

// треугольник на свече i: хотя бы для одной длины выполнены сужение и затухание
inline bool ct_triangle(const Bars& m, int i, int mMin, int mMax, double atrShort, double ratio) {
    if (std::isnan(atrShort)) return false;
    for (int len = mMin; len <= mMax; ++len) {
        const int a = i - len + 1, half = len / 2; if (a < 0) break;
        double h1 = m.h[a], l1 = m.l[a], h2 = m.h[a + half], l2 = m.l[a + half];
        for (int k = a + 1; k < a + half; ++k) { h1 = std::max(h1, m.h[k]); l1 = std::min(l1, m.l[k]); }
        for (int k = a + half + 1; k <= i; ++k) { h2 = std::max(h2, m.h[k]); l2 = std::min(l2, m.l[k]); }
        if (h2 < h1 && l2 > l1 && h1 > l1 && atrShort / (h1 - l1) <= ratio + 1e-9) return true;
    }
    return false;
}

inline CtResult ct_run(const Params& P, const Bars& m, const Bars& h, int start_idx, double comm, bool by_price) {
    auto par = [&](const char* k) { auto it = P.find(k); if (it == P.end()) throw std::runtime_error(std::string("CLASSIC_TRACE_01: нет параметра ") + k); return it->second; };
    const int N = (int)par("fractal_n"), triMin = (int)par("tri_min_bars"), triMax = (int)par("tri_max_bars"), apex = (int)par("apex_bars"), triAtr = (int)par("tri_atr_bars");
    const int winStart = (int)par("window_start_min") * 60, winEnd = (int)par("window_end_min") * 60, atrP = (int)par("atr_period"), maxOut = (int)par("max_outside");
    const int ttl = (int)par("limit_ttl_bars"), spreadDays = (int)par("spread_days"), maxLoss = (int)par("max_losses");
    const double triRatio = par("tri_atr_max"), swMin = par("sweep_min_atr"), swMax = par("sweep_max_atr"), buf = par("sl_buffer_atr"), minRR = par("min_rr"),
                 beFr = par("be_fraction"), body = par("limit_body_part"), eqM = par("eq_spread_mult"), spMult = par("spread_mult"), maxGap = par("max_entry_gap_min") * 60;
    if (m.period_sec != 300 || h.period_sec != 3600) throw std::runtime_error("CLASSIC_TRACE_01 работает на M5 с направлением по H1");

    const int n = (int)m.size(); const double pt = m.point;
    CtResult R; R.sigs.assign(n, 0);
    const std::vector<double> A = lt_atr(m, atrP), A3 = lt_atr(m, triAtr);
    CtStruct S5(m, N, eqM), S1(h, N, eqM); size_t hi = 0;
    auto feed_h1 = [&](int64_t now) { while (hi < h.size() && h.t[hi] + h.period_sec <= now) S1.feed(hi++); };

    struct HourAcc { std::vector<std::pair<double, long>> days; double s = 0; long c = 0; };
    HourAcc H[24];

    int64_t day = -1; int losses = 0;
    // вынос
    bool inEx = false; int dir = 0, outside = 0, peak = 0; double edge = 0, ext = 0, exAtr = 0; std::vector<CtZone> snapOb, snapEq;
    // ордер: kind 1 - по рынку, 2 - лимитный
    int kind = 0, o_sig = 0, o_dir = 0; double o_sl = 0, o_price = 0, o_tp = 0;
    bool pos = false; LtTrade T{}; int tLim = 0; double stop = 0, beTrig = 0, spIn = 0; bool beArmed = false;

    auto close_pos = [&](int i, double px, const char* why) {
        T.i_out = i; T.exit = px; T.why = why;
        T.pnl = (T.dir > 0 ? px - T.entry : T.entry - px) - comm * (by_price ? T.entry : 1.0);
        T.R = T.pnl / std::fabs(T.entry - T.sl);
        if (T.pnl < 0) ++losses;
        R.trades.push_back(T); R.lim.push_back(tLim); pos = false;
    };

    for (int i = 0; i < n; ++i) {
        const int64_t t = m.t[i], dd = t / 86400, sec = t % 86400;
        const bool inTest = i >= start_idx;
        if (dd != day) {
            if (day >= 0) for (int u = 0; u < 24; ++u) { if (!H[u].c) continue; H[u].days.push_back({H[u].s, H[u].c}); if ((int)H[u].days.size() > spreadDays) H[u].days.erase(H[u].days.begin()); H[u].s = 0; H[u].c = 0; }
            day = dd; losses = 0; inEx = false;
        }
        const double sp = m.spread[i] * pt;
        feed_h1(t);

        // 1. ордер на этой свече
        bool intrabar = false;
        auto open_pos = [&](double entry, double tp, bool limit) {
            pos = true; T = LtTrade{o_sig, i, -1, o_dir, entry, 0, o_sl, tp, 0, 0, 0, ""}; tLim = limit ? 1 : 0;
            stop = o_sl; spIn = sp; beArmed = false; beTrig = entry + beFr * (tp - entry);
            if (inTest) ++(limit ? R.f.entries_limit : R.f.entries_market);
        };
        if (kind == 1) {
            kind = 0;
            if (t - (m.t[o_sig] + m.period_sec) > (int64_t)maxGap) { if (inTest) ++R.f.rej_gap; }
            else if (losses >= maxLoss) { if (inTest) ++R.f.rej_losses; }
            else {
                const double entry = o_dir > 0 ? m.o[i] + sp : m.o[i];
                const double tp = S1.target(o_dir, entry);
                if (std::isnan(tp)) { if (inTest) ++R.f.rej_target; }
                else {
                    const double risk = o_dir > 0 ? entry - o_sl : o_sl - entry, reward = o_dir > 0 ? tp - entry : entry - tp;
                    if (!(risk > 0 && reward > 0 && reward / risk >= minRR - 1e-9)) { if (inTest) ++R.f.rej_rr; }
                    else open_pos(entry, tp, false);
                }
            }
        } else if (kind == 2) {
            const double openFill = o_dir > 0 ? m.o[i] + sp : m.o[i];                    // покупка по Ask, продажа по Bid
            const bool beyondStop = o_dir > 0 ? m.o[i] <= o_sl : m.o[i] + sp >= o_sl;
            const bool atOpen = o_dir > 0 ? openFill <= o_price : openFill >= o_price;
            const bool inside = o_dir > 0 ? m.l[i] + sp <= o_price : m.h[i] >= o_price;
            if (beyondStop) { kind = 0; if (inTest) ++R.f.limit_dropped; }
            else if (atOpen || inside) {
                kind = 0;
                if (losses >= maxLoss) { if (inTest) ++R.f.limit_dropped; }
                else { open_pos(atOpen ? openFill : o_price, o_tp, true); intrabar = !atOpen; }
            } else if (i - o_sig >= ttl) { kind = 0; if (inTest) ++R.f.limit_dropped; }
        }

        // 2. позиция на этой свече
        if (pos) {
            const char* lbl = beArmed ? "BE" : "SL";
            if (T.dir > 0) {
                if (i > T.i_in && m.o[i] <= stop) close_pos(i, m.o[i], lbl);
                else if (m.l[i] <= stop) close_pos(i, stop, lbl);
                else if (!intrabar && m.h[i] >= T.tp) close_pos(i, T.tp, "TP");
                else if (!intrabar && !beArmed && m.h[i] >= beTrig) { beArmed = true; T.be = 1; stop = T.entry + spIn; }
            } else {
                const double ao = m.o[i] + sp, ah = m.h[i] + sp, al = m.l[i] + sp;
                if (i > T.i_in && ao >= stop) close_pos(i, ao, lbl);
                else if (ah >= stop) close_pos(i, stop, lbl);
                else if (!intrabar && al <= T.tp) close_pos(i, T.tp, "TP");
                else if (!intrabar && !beArmed && al <= beTrig) { beArmed = true; T.be = 1; stop = T.entry - spIn; }
            }
        }
        const int hour = (int)(sec / 3600);
        H[hour].s += m.spread[i]; H[hour].c++;

        // 3. начало выноса: треугольник на предыдущей свече, ориентиры берутся до этой свечи
        const bool inWin = sec >= winStart && sec < winEnd;
        if (!inWin) inEx = false;
        if (!inEx && inWin && i >= apex && i >= triMax && !std::isnan(A[i - 1]) && A[i - 1] > 0) {
            const int bs = S1.bias();
            if (bs) {
                double e = bs > 0 ? m.l[i - 1] : m.h[i - 1];
                for (int k = i - apex; k < i; ++k) e = bs > 0 ? std::min(e, m.l[k]) : std::max(e, m.h[k]);
                if ((bs > 0 ? m.l[i] < e : m.h[i] > e) && ct_triangle(m, i - 1, triMin, triMax, A3[i - 1], triRatio)) {
                    inEx = true; dir = bs; edge = e; exAtr = A[i - 1]; outside = 0; peak = i; ext = bs > 0 ? m.l[i] : m.h[i];
                    snapOb = bs > 0 ? S5.demand : S5.supply; snapEq = bs > 0 ? S5.eqLow : S5.eqHigh;
                    if (inTest) ++R.f.breakouts;
                }
            }
        }

        // 4. свеча закрылась: уровни и структура
        S5.touch(m.l[i], m.h[i]); S1.touch(m.l[i], m.h[i]);
        S5.feed(i);
        feed_h1(t + m.period_sec);

        // 5. ход выноса и сигнал
        if (!inEx) continue;
        if (dir > 0 ? m.l[i] < ext : m.h[i] > ext) { ext = dir > 0 ? m.l[i] : m.h[i]; peak = i; }
        const double depth = dir > 0 ? edge - ext : ext - edge;
        const bool back = dir > 0 ? m.c[i] > edge : m.c[i] < edge;
        if (!back) ++outside;
        if (depth > swMax * exAtr + 1e-12 || outside > maxOut) { inEx = false; if (inTest) ++R.f.true_moves; continue; }
        if (!back) continue;
        inEx = false;
        if (depth < swMin * exAtr - 1e-12) continue;
        if (i < start_idx - 1) continue;
        R.sigs[i] = dir; if (inTest) ++R.f.returns;
        double s = 0; long c = 0; for (const auto& q : H[hour].days) { s += q.first; c += q.second; }
        if (!c || m.spread[i] > spMult * (s / c) + 1e-12) { if (inTest) ++R.f.rej_spread; continue; }
        if (pos || kind) { if (inTest) ++R.f.rej_busy; continue; }
        if (losses >= maxLoss) { if (inTest) ++R.f.rej_losses; continue; }
        if (i + 1 >= n) continue;
        bool mark = false;
        for (const auto& z : snapOb) if (dir > 0 ? ext <= z.hi : ext >= z.lo) mark = true;
        for (const auto& z : snapEq) if (dir > 0 ? ext < z.lo : ext > z.hi) mark = true;
        const double sl = dir > 0 ? ext - (sp + buf * exAtr) : ext + (sp + buf * exAtr);
        if (mark) { if (inTest) ++R.f.landmark; kind = 1; o_sig = i; o_dir = dir; o_sl = sl; continue; }
        const double price = m.o[peak] + body * (m.c[peak] - m.o[peak]);
        const double tp = S1.target(dir, price);
        if (std::isnan(tp)) { if (inTest) ++R.f.rej_target; continue; }
        const double risk = dir > 0 ? price - sl : sl - price, reward = dir > 0 ? tp - price : price - tp;
        if (!(risk > 0 && reward > 0 && reward / risk >= minRR - 1e-9)) { if (inTest) ++R.f.rej_rr; continue; }
        kind = 2; o_sig = i; o_dir = dir; o_sl = sl; o_price = price; o_tp = tp; if (inTest) ++R.f.limit_placed;
    }
    if (pos) close_pos(n - 1, T.dir > 0 ? m.c[n - 1] : m.c[n - 1] + m.spread[n - 1] * pt, "END");
    return R;
}
