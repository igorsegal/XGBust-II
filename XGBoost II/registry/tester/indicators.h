// indicators.h - причинные индикаторы, считаются из свечей с любыми параметрами.
// Значение индикатора на баре i зависит только от баров 0..i. До прогрева значение NaN.
// Формулы описаны в indicators_catalog.json (поле formula) и должны совпадать с ним.
#pragma once
#include "bars.h"
#include <deque>
#include <algorithm>
#include <limits>

typedef std::vector<double> Vec;
typedef std::map<std::string, Vec> IndOut;
static const double NaNv = std::numeric_limits<double>::quiet_NaN();

inline Vec ind_source(const Bars& b, const std::string& s) {
    size_t n = b.size(); Vec x(n);
    for (size_t i = 0; i < n; ++i) {
        if (s == "close" || s.empty()) x[i] = b.c[i];
        else if (s == "open") x[i] = b.o[i];
        else if (s == "high") x[i] = b.h[i];
        else if (s == "low") x[i] = b.l[i];
        else if (s == "median") x[i] = (b.h[i] + b.l[i]) / 2;
        else if (s == "typical") x[i] = (b.h[i] + b.l[i] + b.c[i]) / 3;
        else throw std::runtime_error("неизвестный источник цены: " + s);
    }
    return x;
}

inline Vec sma_nan(const Vec& x, int p) {
    Vec o(x.size(), NaNv); double s = 0; int cnt = 0;
    for (size_t i = 0; i < x.size(); ++i) {
        if (std::isnan(x[i])) { s = 0; cnt = 0; continue; }
        s += x[i]; ++cnt; if (cnt > p) s -= x[i - p];
        if (cnt >= p && cnt % p == 0) { s = 0; for (int k = 0; k < p; ++k) s += x[i - k]; }   // обнуляем накопленную ошибку суммы
        if (cnt >= p) o[i] = s / p;
    }
    return o;
}
inline Vec ema_nan(const Vec& x, int p) {
    Vec o(x.size(), NaNv); double a = 2.0 / (p + 1), s = 0, e = 0; int cnt = 0;
    for (size_t i = 0; i < x.size(); ++i) {
        if (std::isnan(x[i])) { cnt = 0; s = 0; continue; }
        ++cnt;
        if (cnt < p) { s += x[i]; }
        else if (cnt == p) { s += x[i]; e = s / p; o[i] = e; }
        else { e = a * x[i] + (1 - a) * e; o[i] = e; }
    }
    return o;
}
inline Vec rollmax(const Vec& x, int p) {
    Vec o(x.size(), NaNv); std::deque<size_t> q;
    for (size_t i = 0; i < x.size(); ++i) {
        while (!q.empty() && x[q.back()] <= x[i]) q.pop_back();
        q.push_back(i); if (q.front() + p <= i) q.pop_front();
        if (i + 1 >= (size_t)p) o[i] = x[q.front()];
    }
    return o;
}
inline Vec rollmin(const Vec& x, int p) {
    Vec o(x.size(), NaNv); std::deque<size_t> q;
    for (size_t i = 0; i < x.size(); ++i) {
        while (!q.empty() && x[q.back()] >= x[i]) q.pop_back();
        q.push_back(i); if (q.front() + p <= i) q.pop_front();
        if (i + 1 >= (size_t)p) o[i] = x[q.front()];
    }
    return o;
}
inline Vec true_range(const Bars& b) {
    size_t n = b.size(); Vec tr(n);
    for (size_t i = 0; i < n; ++i) {
        double r = b.h[i] - b.l[i];
        if (i) r = std::max(r, std::max(std::fabs(b.h[i] - b.c[i - 1]), std::fabs(b.l[i] - b.c[i - 1])));
        tr[i] = r;
    }
    return tr;
}
inline int ip(const Params& p, const char* k) {
    auto it = p.find(k); if (it == p.end()) throw std::runtime_error(std::string("нет параметра индикатора: ") + k);
    return (int)it->second;
}
inline double fp(const Params& p, const char* k) {
    auto it = p.find(k); if (it == p.end()) throw std::runtime_error(std::string("нет параметра индикатора: ") + k);
    return it->second;
}


inline Vec wma_nan(const Vec& x, int p) {
    Vec o(x.size(), NaNv); double den = p * (p + 1) / 2.0;
    for (size_t i = (size_t)p - 1; i < x.size(); ++i) {
        double s = 0; bool ok = true;
        for (int k = 0; k < p; ++k) { double v = x[i - p + 1 + k]; if (std::isnan(v)) { ok = false; break; } s += v * (k + 1); }
        if (ok) o[i] = s / den;
    }
    return o;
}
// Линейная регрессия по окну из p значений y[i-p+1..i] против 0..p-1: наклон, значение на конце, R^2.
inline bool linreg_win(const Vec& y, size_t i, int p, double& slope, double& endv, double& r2) {
    if (i + 1 < (size_t)p) return false;
    double xm = (p - 1) / 2.0, ym = 0;
    for (int k = 0; k < p; ++k) { double v = y[i - p + 1 + k]; if (std::isnan(v)) return false; ym += v; }
    ym /= p; double sxy = 0, sxx = 0, syy = 0;
    for (int k = 0; k < p; ++k) { double dx = k - xm, dy = y[i - p + 1 + k] - ym; sxy += dx * dy; sxx += dx * dx; syy += dy * dy; }
    slope = sxx > 0 ? sxy / sxx : 0; endv = ym + slope * ((p - 1) - xm); r2 = (sxx > 0 && syy > 0) ? (sxy * sxy) / (sxx * syy) : 0;
    return true;
}
inline int64_t day_of(int64_t t) { return t >= 0 ? t / 86400 : -((-t + 86399) / 86400); }
inline int64_t sec_of_day(int64_t t) { return t - day_of(t) * 86400; }
inline int weekday_of(int64_t t) { int64_t d = day_of(t) + 3; return (int)(((d % 7) + 7) % 7); }   // 0=понедельник
inline int64_t week_of(int64_t t) { return (day_of(t) + 3) / 7; }
// Для пивотов и VWAP воскресный вечер относится к понедельнику (так же построены бары D1 и таблицы индикаторов).
inline int64_t trading_time(int64_t t) { return weekday_of(t) == 6 ? t + 86400 : t; }

inline IndOut compute_indicator(const std::string& name, const Params& p, const Bars& b, const std::string& source);
inline IndOut compute_indicator2(const std::string& name, const Params& p, const Bars& b, const std::string& source);

inline IndOut compute_indicator(const std::string& name, const Params& p, const Bars& b, const std::string& source) {
    size_t n = b.size(); IndOut R;
    if (name == "SMA") { R["value"] = sma_nan(ind_source(b, source), ip(p, "period")); }
    else if (name == "EMA") { R["value"] = ema_nan(ind_source(b, source), ip(p, "period")); }
    else if (name == "RSI") {
        int per = ip(p, "period"); Vec x = ind_source(b, source), o(n, NaNv); double ag = 0, al = 0;
        for (size_t i = 1; i < n; ++i) {
            double ch = x[i] - x[i - 1], g = ch > 0 ? ch : 0, l = ch < 0 ? -ch : 0;
            if (i <= (size_t)per) { ag += g; al += l; if (i == (size_t)per) { ag /= per; al /= per; } }
            else { ag = (ag * (per - 1) + g) / per; al = (al * (per - 1) + l) / per; }
            if (i >= (size_t)per) o[i] = al == 0 ? 100.0 : 100.0 - 100.0 / (1.0 + ag / al);
        }
        R["value"] = o;
    }
    else if (name == "ATR") { R["value"] = sma_nan(true_range(b), ip(p, "period")); }
    else if (name == "MACD") {
        int f = ip(p, "fast"), s = ip(p, "slow"), g = ip(p, "signal");
        if (f >= s) throw std::runtime_error("MACD: fast должен быть меньше slow");
        Vec x = ind_source(b, source), ef = ema_nan(x, f), es = ema_nan(x, s), line(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(ef[i]) && !std::isnan(es[i])) line[i] = ef[i] - es[i];
        Vec sg = ema_nan(line, g), h(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(sg[i])) h[i] = line[i] - sg[i];
        R["line"] = line; R["signal"] = sg; R["hist"] = h;
    }
    else if (name == "BBANDS") {
        int per = ip(p, "period"); double dev = fp(p, "dev"); Vec x = ind_source(b, source);
        Vec mid = sma_nan(x, per), up(n, NaNv), lo(n, NaNv), w(n, NaNv), pb(n, NaNv);
        for (size_t i = 0; i < n; ++i) {
            if (std::isnan(mid[i])) continue;
            double ss = 0; for (int k = 0; k < per; ++k) { double d = x[i - k] - mid[i]; ss += d * d; }
            double sd = std::sqrt(ss / per); up[i] = mid[i] + dev * sd; lo[i] = mid[i] - dev * sd;
            w[i] = mid[i] != 0 ? (up[i] - lo[i]) / mid[i] : NaNv;
            pb[i] = up[i] != lo[i] ? (x[i] - lo[i]) / (up[i] - lo[i]) : 0.5;
        }
        R["middle"] = mid; R["upper"] = up; R["lower"] = lo; R["width"] = w; R["pctb"] = pb;
    }
    else if (name == "DONCHIAN") {
        int per = ip(p, "period"); Vec hh = rollmax(b.h, per), ll = rollmin(b.l, per), m(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(hh[i])) m[i] = (hh[i] + ll[i]) / 2;
        R["upper"] = hh; R["lower"] = ll; R["mid"] = m;
    }
    else if (name == "STOCH") {
        int kp = ip(p, "k_period"), ks = ip(p, "k_smooth"), dp = ip(p, "d_period");
        Vec hh = rollmax(b.h, kp), ll = rollmin(b.l, kp), raw(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(hh[i])) raw[i] = hh[i] == ll[i] ? 50.0 : 100.0 * (b.c[i] - ll[i]) / (hh[i] - ll[i]);
        Vec k = sma_nan(raw, ks); R["k"] = k; R["d"] = sma_nan(k, dp);
    }
    else if (name == "CCI") {
        int per = ip(p, "period"); Vec tp(n), o(n, NaNv);
        for (size_t i = 0; i < n; ++i) tp[i] = (b.h[i] + b.l[i] + b.c[i]) / 3;
        Vec m = sma_nan(tp, per);
        for (size_t i = 0; i < n; ++i) {
            if (std::isnan(m[i])) continue;
            double md = 0; for (int k = 0; k < per; ++k) md += std::fabs(tp[i - k] - m[i]); md /= per;
            o[i] = md == 0 ? 0.0 : (tp[i] - m[i]) / (0.015 * md);
        }
        R["value"] = o;
    }
    else if (name == "ROC") {
        int per = ip(p, "period"); Vec x = ind_source(b, source), o(n, NaNv);
        for (size_t i = per; i < n; ++i) if (x[i - per] != 0) o[i] = 100.0 * (x[i] / x[i - per] - 1.0);
        R["value"] = o;
    }
    else if (name == "WILLR") {
        int per = ip(p, "period"); Vec hh = rollmax(b.h, per), ll = rollmin(b.l, per), o(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(hh[i])) o[i] = hh[i] == ll[i] ? -50.0 : -100.0 * (hh[i] - b.c[i]) / (hh[i] - ll[i]);
        R["value"] = o;
    }
    else if (name == "ADX") {
        int per = ip(p, "period"); Vec pdi(n, NaNv), mdi(n, NaNv), adx(n, NaNv), dx(n, NaNv), tr = true_range(b);
        double sT = 0, sP = 0, sM = 0, av = 0;
        for (size_t i = 1; i < n; ++i) {
            double up = b.h[i] - b.h[i - 1], dn = b.l[i - 1] - b.l[i];
            double pd = (up > dn && up > 0) ? up : 0, md = (dn > up && dn > 0) ? dn : 0;
            if (i <= (size_t)per) { sT += tr[i]; sP += pd; sM += md; }
            else { sT = sT - sT / per + tr[i]; sP = sP - sP / per + pd; sM = sM - sM / per + md; }
            if (i >= (size_t)per) {
                pdi[i] = sT > 0 ? 100.0 * sP / sT : 0.0; mdi[i] = sT > 0 ? 100.0 * sM / sT : 0.0;
                double sm = pdi[i] + mdi[i]; dx[i] = sm > 0 ? 100.0 * std::fabs(pdi[i] - mdi[i]) / sm : 0.0;
                size_t k = i - per + 1;   // номер значения DX с единицы
                if (k <= (size_t)per) { av += dx[i]; if (k == (size_t)per) { av /= per; adx[i] = av; } }
                else { av = (av * (per - 1) + dx[i]) / per; adx[i] = av; }
            }
        }
        R["adx"] = adx; R["plus_di"] = pdi; R["minus_di"] = mdi;
    }
    else return compute_indicator2(name, p, b, source);
    return R;
}

inline IndOut compute_indicator2(const std::string& name, const Params& p, const Bars& b, const std::string& source) {
    size_t n = b.size(); IndOut R; const double LN2 = std::log(2.0);
    if (name == "WMA") { R["value"] = wma_nan(ind_source(b, source), ip(p, "period")); }
    else if (name == "HMA") {
        int per = ip(p, "period"), half = per / 2, sq = (int)std::floor(std::sqrt((double)per) + 0.5); if (half < 1) half = 1; if (sq < 1) sq = 1;
        Vec x = ind_source(b, source), w1 = wma_nan(x, half), w2 = wma_nan(x, per), d(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(w1[i]) && !std::isnan(w2[i])) d[i] = 2 * w1[i] - w2[i];
        R["value"] = wma_nan(d, sq);
    }
    else if (name == "MFI") {
        int per = ip(p, "period"); Vec tp(n), o(n, NaNv);
        for (size_t i = 0; i < n; ++i) tp[i] = (b.h[i] + b.l[i] + b.c[i]) / 3;
        for (size_t i = per; i < n; ++i) {
            double pos = 0, neg = 0;
            for (int k = 0; k < per; ++k) { size_t j = i - k; double f = tp[j] * b.v[j]; if (tp[j] > tp[j - 1]) pos += f; else if (tp[j] < tp[j - 1]) neg += f; }
            o[i] = neg == 0 ? (pos == 0 ? 50.0 : 100.0) : 100.0 - 100.0 / (1.0 + pos / neg);
        }
        R["value"] = o;
    }
    else if (name == "MOMENTUM") {
        int per = ip(p, "period"); Vec x = ind_source(b, source), o(n, NaNv);
        for (size_t i = per; i < n; ++i) o[i] = x[i] - x[i - per];
        R["value"] = o;
    }
    else if (name == "CMO") {
        int per = ip(p, "period"); Vec x = ind_source(b, source), o(n, NaNv);
        for (size_t i = per; i < n; ++i) {
            double up = 0, dn = 0; for (int k = 0; k < per; ++k) { double ch = x[i - k] - x[i - k - 1]; if (ch > 0) up += ch; else dn -= ch; }
            o[i] = (up + dn) == 0 ? 0.0 : 100.0 * (up - dn) / (up + dn);
        }
        R["value"] = o;
    }
    else if (name == "ULTIMATE") {
        int p1 = ip(p, "p1"), p2 = ip(p, "p2"), p3 = ip(p, "p3");
        if (!(p1 < p2 && p2 < p3)) throw std::runtime_error("ULTIMATE: нужно p1 < p2 < p3");
        Vec bp(n, NaNv), tr(n, NaNv), o(n, NaNv);
        for (size_t i = 1; i < n; ++i) { double lo = std::min(b.l[i], b.c[i - 1]), hi = std::max(b.h[i], b.c[i - 1]); bp[i] = b.c[i] - lo; tr[i] = hi - lo; }
        for (size_t i = p3; i < n; ++i) {
            double a[3]; int pp[3] = {p1, p2, p3};
            for (int q = 0; q < 3; ++q) { double sb = 0, st = 0; for (int k = 0; k < pp[q]; ++k) { sb += bp[i - k]; st += tr[i - k]; } a[q] = st == 0 ? 0.0 : sb / st; }
            o[i] = 100.0 * (4 * a[0] + 2 * a[1] + a[2]) / 7.0;
        }
        R["value"] = o;
    }
    else if (name == "TSI") {
        int lg = ip(p, "long_period"), sh = ip(p, "short_period"); Vec x = ind_source(b, source), m(n, NaNv), am(n, NaNv), o(n, NaNv);
        for (size_t i = 1; i < n; ++i) { m[i] = x[i] - x[i - 1]; am[i] = std::fabs(m[i]); }
        Vec nu = ema_nan(ema_nan(m, lg), sh), de = ema_nan(ema_nan(am, lg), sh);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(nu[i]) && !std::isnan(de[i])) o[i] = de[i] == 0 ? 0.0 : 100.0 * nu[i] / de[i];
        R["value"] = o;
    }
    else if (name == "KELTNER") {
        int per = ip(p, "period"), ap = ip(p, "atr_period"); double mult = fp(p, "mult");
        Vec mid = ema_nan(ind_source(b, source), per), at = sma_nan(true_range(b), ap), up(n, NaNv), lo(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(mid[i]) && !std::isnan(at[i])) { up[i] = mid[i] + mult * at[i]; lo[i] = mid[i] - mult * at[i]; }
        for (size_t i = 0; i < n; ++i) if (std::isnan(at[i])) mid[i] = NaNv;   // все три выхода появляются одновременно
        R["middle"] = mid; R["upper"] = up; R["lower"] = lo;
    }
    else if (name == "STDDEV") {
        int per = ip(p, "period"); Vec x = ind_source(b, source), m = sma_nan(x, per), o(n, NaNv);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(m[i])) { double ss = 0; for (int k = 0; k < per; ++k) { double d = x[i - k] - m[i]; ss += d * d; } o[i] = std::sqrt(ss / per); }
        R["value"] = o;
    }
    else if (name == "PARKINSON") {
        int per = ip(p, "period"); Vec t(n), o(n, NaNv);
        for (size_t i = 0; i < n; ++i) { double r = std::log(b.h[i] / b.l[i]); t[i] = r * r; }
        Vec m = sma_nan(t, per); for (size_t i = 0; i < n; ++i) if (!std::isnan(m[i])) o[i] = std::sqrt(m[i] / (4 * LN2));
        R["value"] = o;
    }
    else if (name == "GARMAN_KLASS") {
        int per = ip(p, "period"); Vec t(n), o(n, NaNv);
        for (size_t i = 0; i < n; ++i) { double r = std::log(b.h[i] / b.l[i]), q = std::log(b.c[i] / b.o[i]); t[i] = 0.5 * r * r - (2 * LN2 - 1) * q * q; }
        Vec m = sma_nan(t, per); for (size_t i = 0; i < n; ++i) if (!std::isnan(m[i])) o[i] = std::sqrt(std::max(0.0, m[i]));
        R["value"] = o;
    }
    else if (name == "AROON") {
        int per = ip(p, "period"); Vec up(n, NaNv), dn(n, NaNv), os(n, NaNv);
        for (size_t i = per; i < n; ++i) {
            size_t ih = i, il = i;
            for (int k = 0; k <= per; ++k) { size_t j = i - k; if (b.h[j] > b.h[ih]) ih = j; if (b.l[j] < b.l[il]) il = j; }   // при равенстве остаётся самый свежий бар
            up[i] = 100.0 * (per - (double)(i - ih)) / per; dn[i] = 100.0 * (per - (double)(i - il)) / per; os[i] = up[i] - dn[i];
        }
        R["up"] = up; R["down"] = dn; R["osc"] = os;
    }
    else if (name == "PSAR") {
        double step = fp(p, "step"), mx = fp(p, "max_step"); Vec sar(n, NaNv), dir(n, NaNv);
        if (n > 2) {
            bool lg = b.c[1] >= b.c[0]; double s = lg ? b.l[0] : b.h[0], ep = lg ? b.h[1] : b.l[1], af = step; sar[1] = s; dir[1] = lg ? 1 : -1;
            for (size_t i = 2; i < n; ++i) {
                s = s + af * (ep - s);
                if (lg) {
                    s = std::min(s, std::min(b.l[i - 1], b.l[i - 2]));
                    if (b.l[i] < s) { lg = false; s = ep; ep = b.l[i]; af = step; }
                    else if (b.h[i] > ep) { ep = b.h[i]; af = std::min(af + step, mx); }
                } else {
                    s = std::max(s, std::max(b.h[i - 1], b.h[i - 2]));
                    if (b.h[i] > s) { lg = true; s = ep; ep = b.h[i]; af = step; }
                    else if (b.l[i] < ep) { ep = b.l[i]; af = std::min(af + step, mx); }
                }
                sar[i] = s; dir[i] = lg ? 1 : -1;
            }
        }
        R["value"] = sar; R["direction"] = dir;
    }
    else if (name == "SUPERTREND") {
        int per = ip(p, "period"); double mult = fp(p, "mult"); Vec at = sma_nan(true_range(b), per), line(n, NaNv), dir(n, NaNv);
        double fu = 0, fl = 0; int tr = 0; bool started = false;
        for (size_t i = 0; i < n; ++i) {
            if (std::isnan(at[i])) continue;
            double hl2 = (b.h[i] + b.l[i]) / 2, bu = hl2 + mult * at[i], bl = hl2 - mult * at[i];
            if (!started) { fu = bu; fl = bl; tr = b.c[i] >= hl2 ? 1 : -1; started = true; }
            else {
                double pfu = fu, pfl = fl;
                fu = (bu < pfu || b.c[i - 1] > pfu) ? bu : pfu;
                fl = (bl > pfl || b.c[i - 1] < pfl) ? bl : pfl;
                if (tr == -1 && b.c[i] > pfu) tr = 1; else if (tr == 1 && b.c[i] < pfl) tr = -1;
            }
            line[i] = tr == 1 ? fl : fu; dir[i] = tr;
        }
        R["value"] = line; R["direction"] = dir;
    }
    else if (name == "ICHIMOKU") {
        int tk = ip(p, "tenkan"), kj = ip(p, "kijun"), sb = ip(p, "senkou_b");
        Vec ht = rollmax(b.h, tk), lt = rollmin(b.l, tk), hk = rollmax(b.h, kj), lk = rollmin(b.l, kj), hs = rollmax(b.h, sb), ls = rollmin(b.l, sb);
        Vec ten(n, NaNv), kij(n, NaNv), sa(n, NaNv), sbv(n, NaNv);
        for (size_t i = 0; i < n; ++i) { if (!std::isnan(ht[i])) ten[i] = (ht[i] + lt[i]) / 2; if (!std::isnan(hk[i])) kij[i] = (hk[i] + lk[i]) / 2; }
        for (size_t i = kj; i < n; ++i) {
            size_t j = i - kj;
            if (!std::isnan(ten[j]) && !std::isnan(kij[j])) sa[i] = (ten[j] + kij[j]) / 2;
            if (!std::isnan(hs[j])) sbv[i] = (hs[j] + ls[j]) / 2;
        }
        R["tenkan"] = ten; R["kijun"] = kij; R["span_a"] = sa; R["span_b"] = sbv;
    }
    else if (name == "VORTEX") {
        int per = ip(p, "period"); Vec tr = true_range(b), pl(n, NaNv), mi(n, NaNv);
        for (size_t i = per; i < n; ++i) {
            double vp = 0, vm = 0, st = 0;
            for (int k = 0; k < per; ++k) { size_t j = i - k; vp += std::fabs(b.h[j] - b.l[j - 1]); vm += std::fabs(b.l[j] - b.h[j - 1]); st += tr[j]; }
            pl[i] = st > 0 ? vp / st : 0.0; mi[i] = st > 0 ? vm / st : 0.0;
        }
        R["plus"] = pl; R["minus"] = mi;
    }
    else if (name == "LINREG") {
        int per = ip(p, "period"); Vec x = ind_source(b, source), sl(n, NaNv), ev(n, NaNv), rr(n, NaNv);
        for (size_t i = 0; i < n; ++i) { double a, e, r; if (linreg_win(x, i, per, a, e, r)) { sl[i] = a; ev[i] = e; rr[i] = r; } }
        R["slope"] = sl; R["value"] = ev; R["r2"] = rr;
    }
    else if (name == "OBV" || name == "OBV_SLOPE") {
        Vec ob(n, 0.0); for (size_t i = 1; i < n; ++i) ob[i] = ob[i - 1] + (b.c[i] > b.c[i - 1] ? b.v[i] : (b.c[i] < b.c[i - 1] ? -b.v[i] : 0.0));
        if (name == "OBV") R["value"] = ob;
        else {
            int per = ip(p, "period"); Vec vm = sma_nan(b.v, per), o(n, NaNv);
            for (size_t i = 0; i < n; ++i) { double a, e, r; if (!std::isnan(vm[i]) && linreg_win(ob, i, per, a, e, r)) o[i] = vm[i] > 0 ? a / vm[i] : 0.0; }
            R["value"] = o;
        }
    }
    else if (name == "VOLRATIO") {
        Vec vm = sma_nan(b.v, ip(p, "period")), o(n, NaNv); for (size_t i = 0; i < n; ++i) if (!std::isnan(vm[i])) o[i] = vm[i] > 0 ? b.v[i] / vm[i] : 1.0;
        R["value"] = o;
    }
    else if (name == "CMF" || name == "AD") {
        Vec mfv(n); for (size_t i = 0; i < n; ++i) mfv[i] = b.h[i] == b.l[i] ? 0.0 : ((b.c[i] - b.l[i]) - (b.h[i] - b.c[i])) / (b.h[i] - b.l[i]) * b.v[i];
        if (name == "AD") { Vec ad(n); double s = 0; for (size_t i = 0; i < n; ++i) { s += mfv[i]; ad[i] = s; } R["value"] = ad; }
        else {
            int per = ip(p, "period"); Vec o(n, NaNv);
            for (size_t i = per - 1; i < n; ++i) { double sm = 0, sv = 0; for (int k = 0; k < per; ++k) { sm += mfv[i - k]; sv += b.v[i - k]; } o[i] = sv > 0 ? sm / sv : 0.0; }
            R["value"] = o;
        }
    }
    else if (name == "VWAP_SESSION") {
        Vec vw(n), ds(n); double cpv = 0, cv = 0; int64_t cd = -1;
        for (size_t i = 0; i < n; ++i) {
            int64_t d = day_of(trading_time(b.t[i])); if (d != cd) { cd = d; cpv = 0; cv = 0; }
            double tp = (b.h[i] + b.l[i] + b.c[i]) / 3; cpv += tp * b.v[i]; cv += b.v[i];
            vw[i] = cv > 0 ? cpv / cv : tp; ds[i] = b.c[i] - vw[i];
        }
        R["vwap"] = vw; R["dist"] = ds;
    }
    else if (name == "FORCE") {
        Vec f(n, NaNv); for (size_t i = 1; i < n; ++i) f[i] = (b.c[i] - b.c[i - 1]) * b.v[i];
        R["value"] = ema_nan(f, ip(p, "period"));
    }
    else if (name == "EOM") {
        Vec r(n, NaNv); for (size_t i = 1; i < n; ++i) { double dm = (b.h[i] + b.l[i]) / 2 - (b.h[i - 1] + b.l[i - 1]) / 2; r[i] = b.v[i] == 0 ? 0.0 : dm * (b.h[i] - b.l[i]) / b.v[i]; }
        R["value"] = sma_nan(r, ip(p, "period"));
    }
    else if (name == "BODY_RATIO" || name == "UPPER_SHADOW" || name == "LOWER_SHADOW" || name == "DOJI") {
        double th = name == "DOJI" ? fp(p, "threshold") : 0; Vec o(n);
        for (size_t i = 0; i < n; ++i) {
            double rg = b.h[i] - b.l[i], body = std::fabs(b.c[i] - b.o[i]);
            if (name == "BODY_RATIO") o[i] = rg > 0 ? body / rg : 0.0;
            else if (name == "UPPER_SHADOW") o[i] = rg > 0 ? (b.h[i] - std::max(b.o[i], b.c[i])) / rg : 0.0;
            else if (name == "LOWER_SHADOW") o[i] = rg > 0 ? (std::min(b.o[i], b.c[i]) - b.l[i]) / rg : 0.0;
            else o[i] = (rg > 0 && body / rg <= th) ? 1.0 : 0.0;
        }
        R["value"] = o;
    }
    else if (name == "GAP") { Vec o(n, NaNv); for (size_t i = 1; i < n; ++i) o[i] = b.o[i] - b.c[i - 1]; R["value"] = o; }
    else if (name == "INSIDE_BAR" || name == "OUTSIDE_BAR") {
        Vec o(n, NaNv);
        for (size_t i = 1; i < n; ++i) o[i] = name == "INSIDE_BAR" ? (b.h[i] < b.h[i - 1] && b.l[i] > b.l[i - 1]) : (b.h[i] > b.h[i - 1] && b.l[i] < b.l[i - 1]);
        R["value"] = o;
    }
    else if (name == "ENGULFING") {
        Vec o(n, NaNv);
        for (size_t i = 1; i < n; ++i) {
            bool bull = b.c[i - 1] < b.o[i - 1] && b.c[i] > b.o[i] && b.o[i] <= b.c[i - 1] && b.c[i] >= b.o[i - 1];
            bool bear = b.c[i - 1] > b.o[i - 1] && b.c[i] < b.o[i] && b.o[i] >= b.c[i - 1] && b.c[i] <= b.o[i - 1];
            o[i] = bull ? 1.0 : (bear ? -1.0 : 0.0);
        }
        R["value"] = o;
    }
    else if (name == "PINBAR") {
        double ratio = fp(p, "ratio"); Vec o(n);
        for (size_t i = 0; i < n; ++i) {
            double body = std::fabs(b.c[i] - b.o[i]), up = b.h[i] - std::max(b.o[i], b.c[i]), lo = std::min(b.o[i], b.c[i]) - b.l[i];
            bool bull = lo > 0 && lo >= ratio * body && up <= body, bear = up > 0 && up >= ratio * body && lo <= body;
            o[i] = bull ? 1.0 : (bear ? -1.0 : 0.0);
        }
        R["value"] = o;
    }
    else if (name == "HIGHEST") { R["value"] = rollmax(b.h, ip(p, "period")); }
    else if (name == "LOWEST") { R["value"] = rollmin(b.l, ip(p, "period")); }
    else if (name == "PIVOT_DAY" || name == "PIVOT_WEEK") {
        bool wk = name == "PIVOT_WEEK"; Vec P(n, NaNv), R1(n, NaNv), S1(n, NaNv), R2(n, NaNv), S2(n, NaNv);
        int64_t cur = -1; double ch = 0, cl = 0, cc = 0, ph = 0, pl2 = 0, pc = 0; bool havePrev = false;
        for (size_t i = 0; i < n; ++i) {
            int64_t k = wk ? week_of(trading_time(b.t[i])) : day_of(trading_time(b.t[i]));
            if (k != cur) { if (cur != -1) { ph = ch; pl2 = cl; pc = cc; havePrev = true; } cur = k; ch = b.h[i]; cl = b.l[i]; }
            else { ch = std::max(ch, b.h[i]); cl = std::min(cl, b.l[i]); }
            cc = b.c[i];
            if (havePrev) { double pv = (ph + pl2 + pc) / 3; P[i] = pv; R1[i] = 2 * pv - pl2; S1[i] = 2 * pv - ph; R2[i] = pv + (ph - pl2); S2[i] = pv - (ph - pl2); }
        }
        R["p"] = P; R["r1"] = R1; R["s1"] = S1; R["r2"] = R2; R["s2"] = S2;
    }
    else if (name == "HOUR" || name == "WEEKDAY" || name == "SESSION" || name == "MINUTE_OF_HOUR" || name == "BAR_OF_DAY") {
        Vec o(n);
        for (size_t i = 0; i < n; ++i) {
            int64_t sd = sec_of_day(b.t[i]);
            if (name == "HOUR") o[i] = (double)(sd / 3600);
            else if (name == "WEEKDAY") o[i] = (double)weekday_of(b.t[i]);
            else if (name == "SESSION") o[i] = (double)(sd / 28800);
            else if (name == "MINUTE_OF_HOUR") o[i] = (double)((sd % 3600) / 60);
            else o[i] = (double)(sd / (b.period_sec > 0 ? b.period_sec : 60));
        }
        R["value"] = o;
    }
    else throw std::runtime_error("индикатор не реализован в тестере: " + name);
    return R;
}
