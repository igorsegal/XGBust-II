// rules/hedge.h - правило HEDGE_ENS_01: ансамбль из 5 простых сигналов с весами Hedge (мультипликативные веса).
// Источник: MQL5, статья 25064 "Hedge (Multiplicative Weights): Blending a Handful of Simple Trading Rules Online".
// Все индикаторы причинные: значение на баре i использует только бары 0..i.
#pragma once
#include "../bars.h"
#include <vector>
#include <cmath>
#include <algorithm>

class HedgeEnsemble : public IRule {
    const Bars* B = nullptr;
    int maFast = 10, maSlow = 50, rsiP = 14, bbP = 20, mF = 12, mS = 26, mG = 9, donP = 20;
    double rsiLo = 30, rsiHi = 70, bbDev = 2.0, T = 2000, thr = 0.20, eta = 0;
    bool donIncl = true;
    std::vector<double> maF_, maS_, rsi_, bbU, bbL, hist;
    std::vector<int> prevVote;           // голоса, поданные на предыдущем баре
    double w[5];
    int lastI = -1;

    static void sma(const std::vector<double>& x, int p, std::vector<double>& out, std::vector<double>* sd = nullptr) {
        size_t n = x.size(); out.assign(n, NAN); if (sd) sd->assign(n, NAN);
        double s = 0, s2 = 0;
        for (size_t i = 0; i < n; ++i) {
            s += x[i]; s2 += x[i] * x[i];
            if (i >= (size_t)p) { s -= x[i - p]; s2 -= x[i - p] * x[i - p]; }
            if (i + 1 >= (size_t)p) {
                out[i] = s / p;
                if (sd) { double v = s2 / p - out[i] * out[i]; (*sd)[i] = v > 0 ? std::sqrt(v) : 0; }
            }
        }
    }
    static void ema(const std::vector<double>& x, int p, std::vector<double>& out) {
        size_t n = x.size(); out.assign(n, NAN); if (n == 0) return;
        double k = 2.0 / (p + 1), e = x[0]; out[0] = e;
        for (size_t i = 1; i < n; ++i) { e = x[i] * k + e * (1 - k); out[i] = e; }
    }
public:
    int warmup() const override { return std::max(std::max(maSlow, bbP), std::max(mS + mG, std::max(rsiP + 1, donP))) + 5; }

    void init(const Params& p, const Bars& bars) override {
        B = &bars;
        auto g = [&](const char* k, double d) { auto it = p.find(k); return it == p.end() ? d : it->second; };
        maFast = (int)g("ma_fast", 10); maSlow = (int)g("ma_slow", 50); rsiP = (int)g("rsi_period", 14);
        rsiLo = g("rsi_lower", 30); rsiHi = g("rsi_upper", 70); bbP = (int)g("bb_period", 20); bbDev = g("bb_deviation", 2.0);
        mF = (int)g("macd_fast", 12); mS = (int)g("macd_slow", 26); mG = (int)g("macd_signal", 9);
        donP = (int)g("donchian_period", 20); donIncl = g("donchian_include_current", 1) != 0;
        T = g("regret_horizon", 2000); thr = g("confidence", 0.20);
        eta = std::sqrt(8.0 * std::log(5.0) / T);
        const auto& c = bars.c; size_t n = bars.size();
        sma(c, maFast, maF_); sma(c, maSlow, maS_);
        std::vector<double> m, sd; sma(c, bbP, m, &sd);
        bbU.assign(n, NAN); bbL.assign(n, NAN);
        for (size_t i = 0; i < n; ++i) if (!std::isnan(m[i])) { bbU[i] = m[i] + bbDev * sd[i]; bbL[i] = m[i] - bbDev * sd[i]; }
        // RSI Уайлдера
        rsi_.assign(n, NAN);
        if (n > (size_t)rsiP) {
            double ag = 0, al = 0;
            for (int i = 1; i <= rsiP; ++i) { double d = c[i] - c[i - 1]; if (d > 0) ag += d; else al -= d; }
            ag /= rsiP; al /= rsiP; rsi_[rsiP] = al == 0 ? 100 : 100 - 100 / (1 + ag / al);
            for (size_t i = rsiP + 1; i < n; ++i) {
                double d = c[i] - c[i - 1];
                ag = (ag * (rsiP - 1) + (d > 0 ? d : 0)) / rsiP; al = (al * (rsiP - 1) + (d < 0 ? -d : 0)) / rsiP;
                rsi_[i] = al == 0 ? 100 : 100 - 100 / (1 + ag / al);
            }
        }
        std::vector<double> ef, es, macd, sig; ema(c, mF, ef); ema(c, mS, es);
        macd.resize(n); for (size_t i = 0; i < n; ++i) macd[i] = ef[i] - es[i];
        ema(macd, mG, sig); hist.assign(n, NAN); for (size_t i = 0; i < n; ++i) hist[i] = macd[i] - sig[i];
        for (int i = 0; i < 5; ++i) w[i] = 0.2;
        prevVote.assign(5, 0); lastI = -1;
    }

    void votes(int i, int* v) const {
        const auto& c = B->c; const auto& h = B->h; const auto& l = B->l;
        v[0] = (std::isnan(maF_[i]) || std::isnan(maS_[i])) ? 0 : (maF_[i] > maS_[i] ? 1 : (maF_[i] < maS_[i] ? -1 : 0));
        v[1] = std::isnan(rsi_[i]) ? 0 : (rsi_[i] < rsiLo ? 1 : (rsi_[i] > rsiHi ? -1 : 0));
        v[2] = std::isnan(bbU[i]) ? 0 : (c[i] > bbU[i] ? 1 : (c[i] < bbL[i] ? -1 : 0));
        v[3] = std::isnan(hist[i]) ? 0 : (hist[i] > 0 ? 1 : (hist[i] < 0 ? -1 : 0));
        // Donchian: окно из donP баров; включая текущий бар (как в статье) или только предыдущие (вариант)
        int hi0 = donIncl ? i - donP + 1 : i - donP, hi1 = donIncl ? i : i - 1;
        if (hi0 < 0) { v[4] = 0; return; }
        double mx = -1e18, mn = 1e18;
        for (int k = hi0; k <= hi1; ++k) { mx = std::max(mx, h[k]); mn = std::min(mn, l[k]); }
        v[4] = c[i] >= mx ? 1 : (c[i] <= mn ? -1 : 0);
    }

    int signal(int i) override {
        if (i != lastI + 1) throw std::runtime_error("HedgeEnsemble: сигналы надо запрашивать подряд");
        lastI = i;
        // 1) обновить веса по голосам, поданным на баре i-1, и фактическому движению бара i
        if (i >= 1) {
            double d = B->c[i] - B->c[i - 1]; int sgn = d > 0 ? 1 : (d < 0 ? -1 : 0);
            bool voted = false; for (int k = 0; k < 5; ++k) if (prevVote[k] != 0) voted = true;
            if (voted) {
                double s = 0;
                for (int k = 0; k < 5; ++k) { double loss = 0.5 - 0.5 * prevVote[k] * sgn; w[k] *= std::exp(-eta * loss); s += w[k]; }
                for (int k = 0; k < 5; ++k) w[k] /= s;
            }
        }
        // 2) новые голоса по бару i
        int v[5]; votes(i, v);
        for (int k = 0; k < 5; ++k) prevVote[k] = v[k];
        if (i < warmup()) return 0;
        double e = 0; for (int k = 0; k < 5; ++k) e += w[k] * v[k];
        return e >= thr ? 1 : (e <= -thr ? -1 : 0);
    }
};
inline std::unique_ptr<IRule> make_hedge() { return std::unique_ptr<IRule>(new HedgeEnsemble()); }
