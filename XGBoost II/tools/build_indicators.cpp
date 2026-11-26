// build_indicators.cpp - table of relative features from the 55 catalog indicators (default parameters).
// Formulas are the tester's own: registry/tester/indicators.h. Usage: build_indicators <quotes_dir> <out_dir> [SYMBOL]
//
// Output <SYMBOL>_<TF>_dev.bin (bars before 2025) and _holdout.bin (2025+, keep for the final check only):
//   64-byte header "EQIND001", int32 version, int32 ncols, int64 nrows, first_time, last_time, int32 period_sec;
//   then int64 bar open time [nrows], then float32 columns one after another [ncols][nrows]; names in columns.txt.
// A row uses only its own and earlier bars, so it is known at bar close = time + period_sec
// (W1: time + 7 days). When joining a higher timeframe take only rows already closed at the decision time.
#include "../registry/tester/bars.h"
#include "../registry/tester/indicators.h"
#include <cstdlib>

static const int64_t HOLDOUT_FROM = 1735689600;   // 2025-01-01 00:00 UTC
static const size_t CHECK_BARS = 20000;           // length of the shortened history for the look-ahead check

// How a raw indicator output becomes a feature (C = close, A = ATR14).
enum Kind { RAW, LEVEL /*(C-x)/A*/, UNITS /*x/A*/, OVER_C /*x/C*/, FLOW /*change of x over 20 bars / volume of 20 bars*/,
            FORCE_N /*x/(A*volSMA20)*/, EOM_N /*x*volSMA20/A^2*/ };
struct Out { const char* out; Kind kind; };
struct Spec { const char* name; Params p; std::vector<Out> outs; };

static std::vector<Spec> specs() {
    auto one = [](Kind k) { return std::vector<Out>{{"value", k}}; };
    return {
        {"SMA", {{"period", 20}}, one(LEVEL)}, {"EMA", {{"period", 20}}, one(LEVEL)}, {"RSI", {{"period", 14}}, one(RAW)},
        {"ATR", {{"period", 14}}, one(OVER_C)},
        {"MACD", {{"fast", 12}, {"slow", 26}, {"signal", 9}}, {{"line", UNITS}, {"signal", UNITS}, {"hist", UNITS}}},
        {"BBANDS", {{"period", 20}, {"dev", 2.0}}, {{"middle", LEVEL}, {"width", RAW}, {"pctb", RAW}}},
        {"DONCHIAN", {{"period", 20}}, {{"upper", LEVEL}, {"lower", LEVEL}, {"mid", LEVEL}}},
        {"STOCH", {{"k_period", 14}, {"k_smooth", 3}, {"d_period", 3}}, {{"k", RAW}, {"d", RAW}}},
        {"CCI", {{"period", 20}}, one(RAW)}, {"ROC", {{"period", 10}}, one(RAW)}, {"WILLR", {{"period", 14}}, one(RAW)},
        {"ADX", {{"period", 14}}, {{"adx", RAW}, {"plus_di", RAW}, {"minus_di", RAW}}},
        {"WMA", {{"period", 20}}, one(LEVEL)}, {"HMA", {{"period", 21}}, one(LEVEL)}, {"MFI", {{"period", 14}}, one(RAW)},
        {"MOMENTUM", {{"period", 10}}, one(UNITS)}, {"CMO", {{"period", 14}}, one(RAW)},
        {"ULTIMATE", {{"p1", 7}, {"p2", 14}, {"p3", 28}}, one(RAW)}, {"TSI", {{"long_period", 25}, {"short_period", 13}}, one(RAW)},
        {"KELTNER", {{"period", 20}, {"atr_period", 10}, {"mult", 2.0}}, {{"middle", LEVEL}, {"upper", LEVEL}, {"lower", LEVEL}}},
        {"STDDEV", {{"period", 20}}, one(UNITS)}, {"PARKINSON", {{"period", 20}}, one(RAW)}, {"GARMAN_KLASS", {{"period", 20}}, one(RAW)},
        {"AROON", {{"period", 25}}, {{"up", RAW}, {"down", RAW}, {"osc", RAW}}},
        {"PSAR", {{"step", 0.02}, {"max_step", 0.2}}, {{"value", LEVEL}, {"direction", RAW}}},
        {"SUPERTREND", {{"period", 10}, {"mult", 3.0}}, {{"value", LEVEL}, {"direction", RAW}}},
        {"ICHIMOKU", {{"tenkan", 9}, {"kijun", 26}, {"senkou_b", 52}}, {{"tenkan", LEVEL}, {"kijun", LEVEL}, {"span_a", LEVEL}, {"span_b", LEVEL}}},
        {"VORTEX", {{"period", 14}}, {{"plus", RAW}, {"minus", RAW}}},
        {"LINREG", {{"period", 20}}, {{"slope", UNITS}, {"value", LEVEL}, {"r2", RAW}}},
        {"OBV", {}, one(FLOW)}, {"OBV_SLOPE", {{"period", 20}}, one(RAW)}, {"VOLRATIO", {{"period", 20}}, one(RAW)},
        {"CMF", {{"period", 20}}, one(RAW)},
        {"AD", {}, {}},                       // change of AD over 20 bars / volume = CMF(20), no separate column
        {"VWAP_SESSION", {}, {{"vwap", LEVEL}}},
        {"FORCE", {{"period", 13}}, one(FORCE_N)}, {"EOM", {{"period", 14}}, one(EOM_N)},
        {"BODY_RATIO", {}, one(RAW)}, {"UPPER_SHADOW", {}, one(RAW)}, {"LOWER_SHADOW", {}, one(RAW)}, {"GAP", {}, one(UNITS)},
        {"INSIDE_BAR", {}, one(RAW)}, {"OUTSIDE_BAR", {}, one(RAW)}, {"ENGULFING", {}, one(RAW)},
        {"PINBAR", {{"ratio", 2.0}}, one(RAW)}, {"DOJI", {{"threshold", 0.1}}, one(RAW)},
        {"HIGHEST", {{"period", 20}}, {}}, {"LOWEST", {{"period", 20}}, {}},   // equal to DONCHIAN upper / lower
        {"PIVOT_DAY", {}, {{"p", LEVEL}, {"r1", LEVEL}, {"s1", LEVEL}, {"r2", LEVEL}, {"s2", LEVEL}}},
        {"PIVOT_WEEK", {}, {{"p", LEVEL}, {"r1", LEVEL}, {"s1", LEVEL}, {"r2", LEVEL}, {"s2", LEVEL}}},
        {"HOUR", {}, one(RAW)}, {"WEEKDAY", {}, one(RAW)}, {"SESSION", {}, one(RAW)}, {"MINUTE_OF_HOUR", {}, one(RAW)},
        {"BAR_OF_DAY", {}, one(RAW)},
    };
}

static std::string lower(std::string s) { for (auto& ch : s) ch = (char)tolower((unsigned char)ch); return s; }

// Our data has Sunday evening bars. For day/week based indicators they belong to Monday (same as in the D1 bars).
static Bars sunday_as_monday(const Bars& b) {
    Bars x = b;
    for (auto& t : x.t) if (weekday_of(t) == 6) t += 86400;
    return x;
}

struct Column { std::string name; std::vector<float> v; };

// All feature columns of one indicator for the given bars.
static std::vector<Column> features(const Spec& s, const Bars& b, const Bars& shifted, const Vec& A, const Vec& vm) {
    std::vector<Column> res; if (s.outs.empty()) return res;
    std::string nm = s.name;
    bool day_based = nm == "PIVOT_DAY" || nm == "PIVOT_WEEK" || nm == "VWAP_SESSION";
    IndOut R = compute_indicator(nm, s.p, day_based ? shifted : b, "close");
    size_t n = b.size();
    for (const Out& o : s.outs) {
        const Vec& x = R.at(o.out);
        Column col; col.name = lower(nm); if (std::string(o.out) != "value") col.name += std::string("_") + o.out;
        const char* suf[] = {"", "_dist", "_atr", "_rel", "_flow20", "_norm", "_norm"};
        col.name += suf[o.kind]; col.v.resize(n);
        double vsum = 0;
        for (size_t i = 0; i < n; ++i) {
            double y = NaNv, a = A[i] > 0 ? A[i] : NaNv;
            if (o.kind == FLOW) { vsum += b.v[i]; if (i >= 20) { vsum -= b.v[i - 20]; y = vsum > 0 ? (x[i] - x[i - 20]) / vsum : 0.0; } }
            else if (o.kind == RAW) y = x[i];
            else if (o.kind == LEVEL) y = (b.c[i] - x[i]) / a;
            else if (o.kind == UNITS) y = x[i] / a;
            else if (o.kind == OVER_C) y = x[i] / b.c[i];
            else if (o.kind == FORCE_N) y = vm[i] > 0 ? x[i] / (a * vm[i]) : NaNv;
            else y = x[i] * vm[i] / (a * a);
            col.v[i] = std::isfinite(y) ? (float)y : std::numeric_limits<float>::quiet_NaN();
        }
        res.push_back(std::move(col));
    }
    return res;
}

static Bars head_of(const Bars& b, size_t k) {
    Bars x = b; x.t.resize(k); x.o.resize(k); x.h.resize(k); x.l.resize(k); x.c.resize(k); x.spread.resize(k); x.v.resize(k); return x;
}

#pragma pack(push, 1)
struct IndHeader { char magic[8]; int32_t version, ncols; int64_t nrows, first_time, last_time; int32_t period_sec; char pad[20]; };
#pragma pack(pop)
static_assert(sizeof(IndHeader) == 64, "header must be 64 bytes");

static void must_write(const void* p, size_t size, size_t n, FILE* f) {
    if (n && fwrite(p, size, n, f) != n) throw std::runtime_error("write failed (disk full?)");
}

int main(int argc, char** argv) {
    try {
        if (argc < 3) { printf("usage: build_indicators <quotes_dir> <out_dir> [SYMBOL] [TIMEFRAME]\n"); return 2; }
        std::string in = argv[1], out = argv[2], sym = argc > 3 ? argv[3] : "EURUSD";
        auto S = specs();
        std::string report = "INDICATOR TABLES " + sym + "\n", names;
        const char* tfs[] = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"};
        const std::string only = argc > 4 ? argv[4] : "";      // пусто: все таймфреймы
        for (const char* tf : tfs) {
            if (!only.empty() && only != tf) continue;
            Bars b = load_xfbar(in + "/" + sym + "_" + tf + ".bin");
            size_t n = b.size(), k = std::min(CHECK_BARS, n * 2 / 3);
            size_t split = std::lower_bound(b.t.begin(), b.t.end(), HOLDOUT_FROM) - b.t.begin();
            printf("%s: %u bars ", tf, (unsigned)n); fflush(stdout);
            std::string path[2] = {out + "/" + sym + "_" + tf + "_dev.bin", out + "/" + sym + "_" + tf + "_holdout.bin"};
            size_t from[2] = {0, split}, to[2] = {split, n};
            int ncols = 1; for (auto& s : S) ncols += (int)s.outs.size();   // +1: spread
            FILE* f[2];
            for (int q = 0; q < 2; ++q) {
                f[q] = fopen((path[q] + ".tmp").c_str(), "wb");
                if (!f[q]) throw std::runtime_error("cannot create " + path[q]);
                IndHeader h; memset(&h, 0, sizeof h); memcpy(h.magic, "EQIND001", 8);
                h.version = 1; h.ncols = ncols; h.nrows = (int64_t)(to[q] - from[q]); h.period_sec = b.period_sec;
                if (h.nrows) { h.first_time = b.t[from[q]]; h.last_time = b.t[to[q] - 1]; }
                must_write(&h, sizeof h, 1, f[q]);
                must_write(b.t.data() + from[q], 8, to[q] - from[q], f[q]);
            }
            Bars sh = sunday_as_monday(b), hb = head_of(b, k), hsh = sunday_as_monday(hb);
            Params p14{{"period", 14}};
            Vec A = compute_indicator("ATR", p14, b, "close").at("value"), vm = sma_nan(b.v, 20);
            Vec hA = compute_indicator("ATR", p14, hb, "close").at("value"), hvm = sma_nan(hb.v, 20);
            int done = 0; names.clear();
            auto put = [&](const Column& c) {
                for (int q = 0; q < 2; ++q) must_write(c.v.data() + from[q], 4, to[q] - from[q], f[q]);
                names += std::to_string(done) + ": " + c.name + "\n"; ++done;
            };
            for (auto& s : S) {
                auto full = features(s, b, sh, A, vm), part = features(s, hb, hsh, hA, hvm);
                for (size_t j = 0; j < full.size(); ++j) {
                    if (k && memcmp(full[j].v.data(), part[j].v.data(), k * 4) != 0)
                        throw std::runtime_error("LOOK-AHEAD CHECK FAILED: " + full[j].name + " " + tf);
                    put(full[j]);
                }
            }
            Column sp; sp.name = "spread_atr"; sp.v.resize(n);
            for (size_t i = 0; i < n; ++i) sp.v[i] = A[i] > 0 ? (float)(b.spread[i] * b.point / A[i]) : std::numeric_limits<float>::quiet_NaN();
            put(sp);
            for (int q = 0; q < 2; ++q) {
                if (fclose(f[q]) != 0) throw std::runtime_error("write failed " + path[q]);
                remove(path[q].c_str());
                if (rename((path[q] + ".tmp").c_str(), path[q].c_str()) != 0) throw std::runtime_error("rename failed " + path[q]);
            }
            if (done != ncols) throw std::runtime_error("column count mismatch");
            char line[200];
            snprintf(line, sizeof line, "%-3s bars %8u  dev(2020-2024) %8u  holdout(2025+) %8u  columns %d  look-ahead check OK (%u bars)\n",
                     tf, (unsigned)n, (unsigned)split, (unsigned)(n - split), ncols, (unsigned)k);
            report += line; printf("OK\n");
        }
        report += "indicators computed from catalog: " + std::to_string(S.size()) + " (AD, HIGHEST, LOWEST duplicate other columns)\n";
        const std::pair<const char*, std::string> txt[] = {{"columns.txt", names}, {"REPORT.txt", report}};
        for (auto& t : txt) {
            FILE* f = fopen((out + "/" + t.first).c_str(), "wb");
            if (!f) throw std::runtime_error(std::string("cannot create ") + t.first);
            must_write(t.second.data(), 1, t.second.size(), f); fclose(f);
        }
        printf("\n%s\nINDICATORS OK\n", report.c_str());
        return 0;
    } catch (const std::exception& e) { printf("\nERROR: %s\n", e.what()); return 1; }
}
