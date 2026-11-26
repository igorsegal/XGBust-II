// tester.cpp - тестер правил из реестра на истории XFBAR001.
// Запуск: tester <config.json> [--selftest] [--exam] [--trades=файл.csv]
// Правила kind=strategy (свои вход, стоп и цель) считаются своим модулем, общий выход через 24 бара к ним не применяется.
// Без --exam считается только разработка: бары после начала экзамена не загружаются.
// --exam открывает закрытый экзамен: только для основного теста, прошедшего разработку, и один раз на версию правила.
// Реестр даёт значения параметров по умолчанию; конфиг теста включает правила и переопределяет параметры.
#include "json_mini.h"
#include "bars.h"
#include "expr_rule.h"
#include "rules/hedge.h"
#include "rules/london_trap.h"
#include "rules/classic_trace.h"
#include "rules/ny_continuation.h"
#include <cstdio>
#include <set>
#include <algorithm>
#include <iostream>
#include <fstream>
#include <ctime>

static const char* VERSION = "tester 2.0";

// ---- таблица реализованных правил: id реестра -> фабрика ----
static std::map<std::string, RuleFactory> factories() {
    return { {"HEDGE_ENS_01", make_hedge} };
}

struct Trade { int i_sig, i_in, i_out; int dir; double pnl, R; int64_t t_in; };

// Сигналы, посчитанные вне тестера (модель): файл "время открытия бара сигнала,сигнал", первая строка - заголовок.
struct SignalRule : IRule {
    std::map<int64_t, int> by; std::vector<int> s;
    explicit SignalRule(const std::string& path) {
        std::ifstream f(path); std::string line;
        if (!f || !std::getline(f, line)) throw std::runtime_error("не открыть файл сигналов: " + path);
        while (std::getline(f, line)) {
            if (line.empty() || line == "\r") continue;
            long long t = 0; int v = 0;
            if (sscanf(line.c_str(), "%lld,%d", &t, &v) != 2 || v < -1 || v > 1 || !by.emplace(t, v).second) throw std::runtime_error("плохая строка в файле сигналов: " + line);
        }
    }
    void init(const Params&, const Bars& b) override {
        s.assign(b.size(), 0); size_t used = 0;
        for (size_t i = 0; i < b.size(); ++i) { auto it = by.find(b.t[i]); if (it != by.end()) { s[i] = it->second; ++used; } }
        if (used != by.size()) throw std::runtime_error("в файле сигналов есть времена, которых нет среди баров разработки");
    }
    int warmup() const override { return 0; }
    int signal(int i) override { return s[i]; }
};

// Дата по Unix-времени без gmtime_r (переносимо на MinGW).
static void civil(int64_t t, int& y, int& m, int& d) {
    int64_t z = t / 86400 + 719468; if (t < 0 && t % 86400) z -= 1;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097; int64_t doe = z - era * 146097;
    int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; int64_t yy = yoe + era * 400;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100); int64_t mp = (5 * doy + 2) / 153;
    d = (int)(doy - (153 * mp + 2) / 5 + 1); m = (int)(mp < 10 ? mp + 3 : mp - 9); y = (int)(yy + (m <= 2));
}
static std::string ymd(int64_t t) { int y, m, d; civil(t, y, m, d); char b[32]; snprintf(b, sizeof b, "%04d-%02d-%02d", y % 10000, m, d); return b; }
static std::string quarter(int64_t t) { int y, m, d; civil(t, y, m, d); char b[32]; snprintf(b, sizeof b, "%04dQ%d", y % 10000, (m - 1) / 3 + 1); return b; }

struct Seg { std::string name; int64_t t0, t1; };   // [t0, t1)
struct Metrics { int n = 0, wins = 0, longs = 0, shorts = 0; double net = 0, gw = 0, gl = 0, sumR = 0, maxdd = 0; int posQ = 0, totQ = 0; };

static Metrics calc(const std::vector<Trade>& tr, const Seg& s, double point) {
    Metrics m; double eq = 0, peak = 0; std::map<std::string, double> q;
    for (const auto& t : tr) {
        if (t.t_in < s.t0 || t.t_in >= s.t1) continue;
        m.n++; double p = t.pnl / (10 * point);   // в пипсах (5-значная котировка)
        m.net += p; (p > 0 ? m.gw : m.gl) += (p > 0 ? p : -p); if (p > 0) m.wins++;
        (t.dir > 0 ? m.longs : m.shorts)++; m.sumR += t.R;
        eq += p; peak = std::max(peak, eq); m.maxdd = std::max(m.maxdd, peak - eq); q[quarter(t.t_in)] += p;
    }
    m.totQ = (int)q.size(); for (auto& kv : q) if (kv.second > 0) m.posQ++;
    return m;
}
static double pf(const Metrics& m) { return m.gl > 0 ? m.gw / m.gl : (m.gw > 0 ? 999 : 0); }

// ATR (простое среднее TR за period), причинный
static std::vector<double> atr(const Bars& b, int p) {
    size_t n = b.size(); std::vector<double> tr(n), a(n, NAN);
    for (size_t i = 0; i < n; ++i) {
        double r = b.h[i] - b.l[i];
        if (i) r = std::max(r, std::max(std::fabs(b.h[i] - b.c[i - 1]), std::fabs(b.l[i] - b.c[i - 1])));
        tr[i] = r;
    }
    double s = 0; for (size_t i = 0; i < n; ++i) { s += tr[i]; if (i >= (size_t)p) s -= tr[i - p]; if (i + 1 >= (size_t)p) a[i] = s / p; }
    return a;
}

// comm - комиссия за единицу лота в долларах; comm_by_price: котировка не в долларах (USDJPY), доллары переводятся по цене входа.
struct ExitCfg { int hold; double stopMult; int atrP; double comm; bool comm_by_price; };

static std::vector<Trade> simulate(IRule& rule, const Bars& b, const std::vector<double>& A, int start_idx, const ExitCfg& X, std::vector<int>* sigs) {
    std::vector<Trade> out; int n = (int)b.size(); int free_from = 0;
    if (sigs) sigs->assign(n, 0);
    for (int x = 0; x < n - 1; ++x) {
        int sg = rule.signal(x);
        if (sigs) (*sigs)[x] = sg;
        if (sg == 0 || x < start_idx - 1 || x < free_from || std::isnan(A[x]) || A[x] <= 0) continue;
        int e = x + 1; if (e + X.hold - 1 >= n) break;
        double dist = X.stopMult * A[x], sp = b.spread[e] * b.point;
        double entry = sg > 0 ? b.o[e] + sp : b.o[e];
        double stop = sg > 0 ? entry - dist : entry + dist;
        int k = e; double exitp = 0; bool done = false;
        for (k = e; k <= e + X.hold - 1; ++k) {
            if (sg > 0) {
                if (k > e && b.o[k] <= stop) { exitp = b.o[k]; done = true; break; }
                if (b.l[k] <= stop) { exitp = stop; done = true; break; }
            } else {
                double ask_o = b.o[k] + b.spread[k] * b.point, ask_h = b.h[k] + b.spread[k] * b.point;
                if (k > e && ask_o >= stop) { exitp = ask_o; done = true; break; }
                if (ask_h >= stop) { exitp = stop; done = true; break; }
            }
        }
        if (!done) { k = e + X.hold - 1; exitp = sg > 0 ? b.c[k] : b.c[k] + b.spread[k] * b.point; }
        double pnl = (sg > 0 ? exitp - entry : entry - exitp) - X.comm * (X.comm_by_price ? entry : 1.0);
        out.push_back({x, e, k, sg, pnl, pnl / dist, b.t[e]});
        free_from = k;
    }
    return out;
}

// ---- скользящие окна: обучение train месяцев, проверка test месяцев, сдвиг = test ----
static int month_index(const std::string& s) {
    int y = 0, m = 0; if (s.size() != 7 || sscanf(s.c_str(), "%d-%d", &y, &m) != 2 || m < 1 || m > 12) throw std::runtime_error("месяц должен быть в виде ГГГГ-ММ: " + s);
    return y * 12 + m - 1;
}
static int64_t month_start(int idx) {   // Unix-время 00:00 UTC первого числа месяца
    int y = idx / 12, m = idx % 12 + 1; y -= m <= 2;
    int64_t era = y / 400, yoe = y - era * 400, doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5, doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return (era * 146097 + doe - 719468) * 86400;
}
struct Win { int n; int64_t train0, t0, t1; };
struct Plan { int train, test; int dev_from, exam_from, exam_to; };
// Окна разработки или экзамена. Берутся только окна, для которых в истории есть всё обучение (допуск 5 дней на выходные).
static std::vector<Win> windows(const Plan& P, int64_t first_bar, bool exam) {
    std::vector<Win> w; int ndev = 0;
    for (int s = P.dev_from + P.train; s + P.test <= P.exam_from; s += P.test) ++ndev;
    int start = exam ? P.exam_from : P.dev_from + P.train, num = exam ? ndev + 1 : 1;
    for (int s = start; exam ? s <= P.exam_to : s + P.test <= P.exam_from; s += P.test, ++num) {
        if (first_bar > month_start(s - P.train) + 5 * 86400) continue;
        int end = s + P.test; if (exam && end > P.exam_to + 1) end = P.exam_to + 1;
        w.push_back({num, month_start(s - P.train), month_start(s), month_start(end)});
    }
    return w;
}

static std::string num_s(double v) { char b[40]; snprintf(b, sizeof b, "%.10g", v); return b; }

// Режим проверки индикатора: tester --dump <файл баров> <ИНДИКАТОР> <выход> <источник> [имя=значение ...]
// Печатает по одному значению на бар (nan до прогрева). Нужен для независимой сверки с Python.
static int dump_indicator(int argc, char** argv) {
    if (argc < 6) { std::cerr << "Использование: tester --dump <файл баров> <ИНДИКАТОР> <выход> <источник> [имя=значение ...]\n"; return 2; }
    Bars b = load_xfbar(argv[2]); Params p;
    for (int i = 6; i < argc; ++i) { std::string a = argv[i]; size_t e = a.find('='); if (e == std::string::npos) throw std::runtime_error("параметр должен быть имя=значение: " + a); p[a.substr(0, e)] = atof(a.c_str() + e + 1); }
    IndOut r = compute_indicator(argv[3], p, b, argv[5]);
    if (!r.count(argv[4])) throw std::runtime_error(std::string("нет выхода ") + argv[4]);
    const Vec& v = r[argv[4]];
    for (size_t i = 0; i < v.size(); ++i) { if (std::isnan(v[i])) printf("%lld nan\n", (long long)b.t[i]); else printf("%lld %.15g\n", (long long)b.t[i], v[i]); }
    return 0;
}

// ---- стратегии со своими выходами ----
struct Strat { std::vector<LtTrade> trades; std::vector<int> sigs, lim; std::string fjson, ftext; };
static bool has_strategy(const std::string& id) { return id == "LONDON_TRAP_01" || id == "CLASSIC_TRACE_01" || id == "NY_CONTINUATION_01"; }
static std::string funnel_str(std::initializer_list<std::pair<const char*, long>> v, bool json) {
    std::string r; for (const auto& kv : v) { if (!r.empty()) r += json ? "," : ", "; r += json ? "\"" + std::string(kv.first) + "\":" + std::to_string(kv.second) : std::string(kv.first) + " " + std::to_string(kv.second); }
    return json ? "{" + r + "}" : r;
}
static Strat run_strategy(const std::string& id, const Params& P, const Bars& m, const Bars& h, BarCache& cache, int start, double comm, bool by_price) {
    Strat s;
    if (id == "LONDON_TRAP_01") {
        LtResult r = lt_run(P, m, h, cache.get("D1"), start, comm, by_price); const LtFunnel& f = r.f;
        s.trades = r.trades; s.sigs = r.sigs; s.lim.assign(r.trades.size(), 0);
        auto text = [&](bool json) { return funnel_str({{"days", f.days}, {"days_bias", f.bias}, {"days_asia_ok", f.asia_ok}, {"days_ready", f.ready}, {"days_swept", f.swept}, {"true_moves", f.true_move}, {"returns", f.returns},
            {"rej_spread", f.rej_spread}, {"rej_busy", f.rej_busy}, {"rej_gap", f.rej_gap}, {"rej_losses", f.rej_losses}, {"rej_rr", f.rej_rr}, {"entries", f.entries}}, json); };
        s.fjson = text(true); s.ftext = text(false);
    } else if (id == "NY_CONTINUATION_01") {
        NyResult r = ny_run(P, m, h, start, comm, by_price); const NyFunnel& f = r.f;
        s.trades = r.trades; s.sigs = r.sigs; s.lim.assign(r.trades.size(), 0);
        auto text = [&](bool json) { return funnel_str({{"days", f.days}, {"days_bias", f.bias}, {"days_impulse", f.impulse}, {"days_pullback", f.pullback}, {"days_too_deep", f.too_deep}, {"signals", f.signals},
            {"rej_spread", f.rej_spread}, {"rej_busy", f.rej_busy}, {"rej_losses", f.rej_losses}, {"rej_gap", f.rej_gap}, {"rej_target", f.rej_target}, {"rej_rr", f.rej_rr}, {"entries", f.entries}}, json); };
        s.fjson = text(true); s.ftext = text(false);
    } else {
        CtResult r = ct_run(P, m, h, start, comm, by_price); const CtFunnel& f = r.f;
        s.trades = r.trades; s.sigs = r.sigs; s.lim = r.lim;
        auto text = [&](bool json) { return funnel_str({{"breakouts", f.breakouts}, {"true_moves", f.true_moves}, {"returns", f.returns}, {"rej_spread", f.rej_spread}, {"rej_busy", f.rej_busy}, {"rej_losses", f.rej_losses},
            {"landmark", f.landmark}, {"rej_gap", f.rej_gap}, {"rej_target", f.rej_target}, {"rej_rr", f.rej_rr}, {"limit_placed", f.limit_placed}, {"limit_dropped", f.limit_dropped}, {"entries_market", f.entries_market}, {"entries_limit", f.entries_limit}}, json); };
        s.fjson = text(true); s.ftext = text(false);
    }
    return s;
}
static std::vector<Trade> strat_trades(const Strat& r, const Bars& b) {
    std::vector<Trade> out; for (const auto& t : r.trades) out.push_back({t.i_sig, t.i_in, t.i_out, t.dir, t.pnl, t.R, b.t[t.i_in]}); return out;
}
static void write_trades(const std::string& path, const Strat& r, const Bars& b) {
    FILE* f = fopen(path.c_str(), "wb"); if (!f) throw std::runtime_error("не записать сделки: " + path);
    fprintf(f, "signal_time,entry_time,exit_time,dir,entry,exit,sl,tp,pnl,R,be,why,limit\n");
    for (size_t k = 0; k < r.trades.size(); ++k) { const LtTrade& t = r.trades[k];
        fprintf(f, "%lld,%lld,%lld,%d,%.10g,%.10g,%.10g,%.10g,%.10g,%.10g,%d,%s,%d\n",
            (long long)b.t[t.i_sig], (long long)b.t[t.i_in], (long long)b.t[t.i_out], t.dir, t.entry, t.exit, t.sl, t.tp, t.pnl, t.R, t.be, t.why.c_str(), r.lim[k]); }
    fclose(f);
}

// Порча баров после точки среза (для проверки причинности): бар j портится, если он закрывается позже cut_t.
static void scramble(Bars& b, int64_t cut_t) {
    for (size_t i = 0; i < b.size(); ++i) if (b.t[i] + b.period_sec > cut_t) { b.o[i] *= 1.37; b.h[i] *= 1.41; b.l[i] *= 0.63; b.c[i] = b.c[i] * 0.77 + 0.1; }
}

int main(int argc, char** argv) {
    try {
        if (argc >= 2 && std::string(argv[1]) == "--dump") return dump_indicator(argc, argv);
        if (argc < 2) { std::cerr << "Использование: tester <config.json> [--selftest] [--exam] [--trades=файл] [--signals=файл]\n"; return 2; }
        bool selftest = false, exam = false; std::string tradesPath, signalsPath;
        for (int i = 2; i < argc; ++i) {
            std::string a = argv[i];
            if (a == "--selftest") selftest = true; else if (a == "--exam") exam = true; else if (a.rfind("--trades=", 0) == 0) tradesPath = a.substr(9); else if (a.rfind("--signals=", 0) == 0) signalsPath = a.substr(10); else throw std::runtime_error("неизвестный ключ: " + a);
        }
        std::string cfgPath = argv[1];
        JV cfg = json_load(cfgPath);
        std::string dir = cfgPath.substr(0, cfgPath.find_last_of("/\\") == std::string::npos ? 0 : cfgPath.find_last_of("/\\") + 1);
        std::string regPath = cfg.has("registry") ? cfg.at("registry").str() : dir + "../rules_registry.json";
        if (!cfg.has("registry") && dir.empty()) regPath = "../rules_registry.json";
        JV reg = json_load(regPath);
        std::string regDir = regPath.substr(0, regPath.find_last_of("/\\") == std::string::npos ? 0 : regPath.find_last_of("/\\") + 1);
        JV catJ = json_load(cfg.has("catalog") ? cfg.at("catalog").str() : regDir + "indicators_catalog.json");
        std::map<std::string, JV> catalog; for (const auto& ij : catJ.at("indicators").a) catalog[ij.at("id").str()] = ij;

        const JV& d = cfg.at("data");
        std::string pair = d.at("pair").str(), tf = d.at("timeframe").str(), bdir = d.at("bars_dir").str();
        char sep = bdir.find('\\') != std::string::npos ? '\\' : '/';
        const std::string barsPath = bdir + sep + pair + sep + pair + "_" + tf + ".bin";
        std::string testName = cfg.at("test_name").str();
        std::string role = cfg.has("role") ? cfg.at("role").str() : std::string("primary");

        const JV& per = cfg.at("period");
        Plan PL; PL.train = (int)per.at("train_months").num(6); PL.test = (int)per.at("test_months").num(2);
        PL.dev_from = month_index(per.at("dev_from").str()); PL.exam_from = month_index(per.at("exam_from").str()); PL.exam_to = month_index(per.at("exam_to").str());
        if (PL.train < 1 || PL.test < 1 || (int)per.at("step_months").num(2) != PL.test) throw std::runtime_error("нужно: обучение и проверка от 1 месяца, сдвиг равен проверке");

        const JV& cs = cfg.at("costs"), &ex = cfg.at("exits");
        ExitCfg X; X.hold = ex.has("hold_bars") ? (int)ex.at("hold_bars").num(24) : 24; X.stopMult = ex.has("stop_atr_mult") ? ex.at("stop_atr_mult").num(2.0) : 2.0; X.atrP = ex.has("atr_period") ? (int)ex.at("atr_period").num(14) : 14;
        if (pair.size() != 6 || (pair.substr(3) != "USD" && pair.substr(0, 3) != "USD")) throw std::runtime_error("комиссия умеет только инструменты с USD: " + pair);
        const double lot = pair.substr(0, 3) == "XAU" ? 100.0 : 100000.0;     // золото: лот 100 унций
        if (cs.has("lot_units") && cs.at("lot_units").num(lot) != lot) throw std::runtime_error("lot_units в конфиге не соответствует инструменту " + pair);
        X.comm = cs.at("commission_per_lot_usd").num(7) / lot; X.comm_by_price = pair.substr(3) != "USD";
        const JV& cr = cfg.at("criteria");
        int minTrades = (int)cr.at("min_trades").num(100); double minPF = cr.at("min_profit_factor").num(1.3);

        // разработка: бары, закрывающиеся после начала экзамена, отрезаются при загрузке
        const int64_t devCut = month_start(PL.exam_from), examCut = month_start(PL.exam_to + 1);
        Bars full = load_xfbar(barsPath);
        if (full.size() == 0) throw std::runtime_error("пустой файл баров");
        const int64_t firstBar = full.t.front();
        Bars b = full; cut_bars(b, devCut);
        std::vector<Win> wDev = windows(PL, firstBar, false), wExam = windows(PL, firstBar, true);
        while (!wExam.empty() && !full.t.empty() && wExam.back().t0 >= full.t.back() + full.period_sec) wExam.pop_back();
        if (b.size() == 0 || wDev.empty()) throw std::runtime_error("для разработки нет данных");

        auto fac = factories();
        std::string head = " \"tester\":\"" + std::string(VERSION) + "\",\n \"test_name\":\"" + testName + "\",\n \"pair\":\"" + pair + "\", \"timeframe\":\"" + tf + "\",\n";
        head += " \"role\":\"" + role + "\",\n \"scheme\":\"" + std::to_string(PL.train) + "+" + std::to_string(PL.test) + "\",\n";
        std::string costs = " \"costs\":{\"commission_per_lot_usd\":" + num_s(cs.at("commission_per_lot_usd").num(7)) + ",\"lot_units\":" + num_s(lot) + ",\"spread\":\"по бару из файла\"},\n";
        if (ex.has("by_rule") && ex.at("by_rule").boolean(false)) costs += " \"exits\":{\"by_rule\":true},\n";
        else costs += " \"exits\":{\"hold_bars\":" + std::to_string(X.hold) + ",\"stop_atr_mult\":" + num_s(X.stopMult) + "},\n";
        std::string devRules, examRules; int exitCode = 0, examDone = 0;

        // прогон одного правила по отрезку (окна идут подряд): возвращает JSON и признак прохождения
        auto report = [&](const std::string& id, const std::string& over, const char* seg, const std::vector<Win>& W,
                          const Bars& bb, const std::vector<Trade>& tr, const std::vector<int>& sigs, bool& ok) {
            Seg all{seg, W.front().t0, W.back().t1}; Metrics m = calc(tr, all, bb.point);
            long long nsig = 0; for (size_t i = 0; i < bb.size(); ++i) if (sigs[i] && bb.t[i] >= all.t0 && bb.t[i] < all.t1) ++nsig;
            std::string wj; int pos = 0;
            for (const auto& w : W) {
                Metrics q = calc(tr, Seg{"w", w.t0, w.t1}, bb.point); if (q.net > 0) ++pos;
                char buf[200]; snprintf(buf, sizeof buf, "%s{\"n\":%d,\"from\":\"%s\",\"to\":\"%s\",\"trades\":%d,\"net_pips\":%.1f}", wj.empty() ? "" : ",", w.n, ymd(w.t0).c_str(), ymd(w.t1 - 1).c_str(), q.n, q.net);
                wj += buf;
            }
            ok = m.n >= minTrades && m.net > 0 && pf(m) >= minPF;
            printf("  %s: окна %d..%d, %s..%s\n  сделок %d (лонг %d, шорт %d)  побед %.1f%%  нетто %.1f пп  PF %.2f  ср.R %.3f  макс.просадка %.1f пп  плюсовых окон %d/%d\n",
                   seg, W.front().n, W.back().n, ymd(all.t0).c_str(), ymd(all.t1 - 1).c_str(), m.n, m.longs, m.shorts, m.n ? 100.0 * m.wins / m.n : 0.0, m.net, pf(m), m.n ? m.sumR / m.n : 0.0, m.maxdd, pos, (int)W.size());
            printf("  ВЕРДИКТ (%s): %s (нужно: сделок >= %d, нетто > 0, PF >= %.2f)\n", seg, ok ? "ПРОШЛО" : "НЕ ПРОШЛО", minTrades, minPF);
            char buf[600]; snprintf(buf, sizeof buf, "{\"segment\":\"%s\",\"from\":\"%s\",\"to\":\"%s\",\"trades\":%d,\"win_pct\":%.2f,\"net_pips\":%.1f,\"profit_factor\":%.3f,\"avg_R\":%.4f,\"max_dd_pips\":%.1f,\"pos_windows\":\"%d/%d\"}",
                     seg, ymd(all.t0).c_str(), ymd(all.t1 - 1).c_str(), m.n, m.n ? 100.0 * m.wins / m.n : 0.0, m.net, pf(m), m.n ? m.sumR / m.n : 0.0, m.maxdd, pos, (int)W.size());
            return "  {\"id\":\"" + id + "\", \"overrides\":\"" + over + "\", \"signals_total\":" + std::to_string(nsig) + ", \"segments\":[" + buf + "],\n   \"windows\":[" + wj + "],\n   \"verdict\":\"" + (ok ? "PASS" : "FAIL") + "\"}";
        };
        auto first_at = [](const Bars& bb, int64_t t) { int i = 0; while (i < (int)bb.size() && bb.t[i] < t) ++i; return i; };

        for (const auto& rj : reg.at("rules").a) {
            std::string id = rj.at("id").str();
            if (!cfg.at("rules").has(id)) continue;
            const JV& rc = cfg.at("rules").at(id);
            if (!rc.at("enabled").boolean(false)) { printf("[%s] выключено в конфиге\n", id.c_str()); continue; }
            bool isExpr = rj.has("implementation") && rj.at("implementation").t == JV::OBJ && rj.at("implementation").has("kind") && rj.at("implementation").at("kind").str() == "expr";
            bool isStrat = rj.has("implementation") && rj.at("implementation").t == JV::OBJ && rj.at("implementation").has("kind") && rj.at("implementation").at("kind").str() == "strategy";
            bool isSig = rj.has("implementation") && rj.at("implementation").t == JV::OBJ && rj.at("implementation").has("kind") && rj.at("implementation").at("kind").str() == "signals";
            const bool byRule = ex.has("by_rule") && ex.at("by_rule").boolean(false);
            if (isStrat != byRule) throw std::runtime_error("[" + id + "] в конфиге exits.by_rule должно быть true только для правил со своими выходами");
            if (isStrat && !has_strategy(id)) { printf("[%s] ВКЛЮЧЕНО, но реализации в тестере нет\n", id.c_str()); exitCode = 3; continue; }
            if (isSig && signalsPath.empty()) { printf("[%s] ВКЛЮЧЕНО, но не задан файл сигналов (--signals=)\n", id.c_str()); exitCode = 3; continue; }
            if (!isExpr && !isStrat && !isSig && !fac.count(id)) { printf("[%s] ВКЛЮЧЕНО, но реализации в тестере нет\n", id.c_str()); exitCode = 3; continue; }
            Params P;
            for (const auto& kv : rj.at("params").o) P[kv.first] = kv.second.at("default").num(0);
            std::string over;
            if (rc.has("params")) for (const auto& kv : rc.at("params").o) {
                if (!rj.at("params").has(kv.first)) throw std::runtime_error("[" + id + "] параметра '" + kv.first + "' нет в реестре");
                const JV& pd = rj.at("params").at(kv.first); double v = kv.second.num(0);
                if (pd.has("min") && v < pd.at("min").num(-1e300)) throw std::runtime_error("[" + id + "] параметр " + kv.first + " меньше минимума");
                if (pd.has("max") && v > pd.at("max").num(1e300)) throw std::runtime_error("[" + id + "] параметр " + kv.first + " больше максимума");
                P[kv.first] = v; over += kv.first + "=" + std::to_string(v) + " ";
            }
            BarCache cache; cache.dir = bdir; cache.pair = pair; cache.cutoff = devCut;
            std::unique_ptr<IRule> rule;
            std::vector<int> sigs; std::vector<Trade> tr; Strat lt;
            if (isStrat) {
                lt = run_strategy(id, P, b, cache.get("H1"), cache, first_at(b, wDev.front().t0), X.comm, X.comm_by_price);
                sigs = lt.sigs; tr = strat_trades(lt, b);
                if (!tradesPath.empty()) write_trades(tradesPath, lt, b);
            } else {
                if (isExpr) rule.reset(new ExprRule(rj, P, b, cache, catalog));
                else if (isSig) { rule.reset(new SignalRule(signalsPath)); rule->init(P, b); }
                else { rule = fac[id](); rule->init(P, b); }
                std::vector<double> A = atr(b, X.atrP);
                tr = simulate(*rule, b, A, first_at(b, wDev.front().t0), X, &sigs);
            }

            if (selftest && isStrat) {
                // портим все свечи (M5, H1, D1, включая спред), закрывающиеся после среза: сигналы, входы и закрытые сделки до среза не меняются
                int diff = 0, checked = 0; const double fr[] = {0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9};
                for (double f : fr) {
                    int cut = (int)(b.size() * f); const int64_t cutT = b.t[cut];
                    auto spoil = [&](Bars& x) { scramble(x, cutT); for (size_t i = 0; i < x.size(); ++i) if (x.t[i] + x.period_sec > cutT) x.spread[i] = x.spread[i] * 3 + 7; };
                    Bars m2 = b; spoil(m2); BarCache c2 = cache; for (auto& kv : c2.m) spoil(kv.second);
                    Strat r2 = run_strategy(id, P, m2, c2.get("H1"), c2, first_at(b, wDev.front().t0), X.comm, X.comm_by_price);
                    for (int i = 0; i < cut; ++i) if (r2.sigs[i] != sigs[i]) ++diff;
                    std::vector<LtTrade> a1, a2; for (const auto& t : lt.trades) if (t.i_in < cut) a1.push_back(t); for (const auto& t : r2.trades) if (t.i_in < cut) a2.push_back(t);
                    if (a1.size() != a2.size()) { ++diff; continue; }
                    for (size_t k = 0; k < a1.size(); ++k) {
                        const LtTrade &u = a1[k], &v = a2[k]; ++checked;
                        if (u.i_in != v.i_in || u.dir != v.dir || u.entry != v.entry || u.sl != v.sl || u.tp != v.tp) ++diff;
                        else if ((u.i_out < cut || v.i_out < cut) && (u.i_out != v.i_out || u.exit != v.exit || u.pnl != v.pnl)) ++diff;
                    }
                }
                printf("[%s] SELFTEST причинности (8 точек среза): проверено сделок %d, расхождений %d -> %s\n", id.c_str(), checked, diff, diff == 0 ? "OK" : "ЕСТЬ ЗАГЛЯДЫВАНИЕ");
                if (diff) { exitCode = 4; if (exam) { printf("[%s] экзамен не открыт: проверка причинности не пройдена\n", id.c_str()); continue; } }
            }

            if (selftest && isSig) printf("[%s] SELFTEST: сигналы посчитаны вне тестера, причинность проверяет программа модели\n", id.c_str());
            if (selftest && !isStrat && !isSig) {
                // Проверка на заглядывание в будущее: для нескольких точек среза портим все бары, закрывающиеся после среза,
                // и сравниваем всё, что правило видит до среза: сигналы, а у правил-условий ещё и значения всех индикаторов на каждом баре.
                int totalDiff = 0, totalSer = 0; const double fr[] = {0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9};
                for (double f : fr) {
                    int cut = (int)(b.size() * f); Bars b2 = b;
                    for (size_t i = cut; i < b2.size(); ++i) { b2.o[i] = b.o[i] * 1.37; b2.h[i] = b.h[i] * 1.41; b2.l[i] = b.l[i] * 0.63; b2.c[i] = b.c[i] * 0.77 + 0.1; }
                    BarCache cache2 = cache; for (auto& kv : cache2.m) scramble(kv.second, b.t[cut]);
                    std::unique_ptr<IRule> r2;
                    if (isExpr) r2.reset(new ExprRule(rj, P, b2, cache2, catalog)); else { r2 = fac[id](); r2->init(P, b2); }
                    for (int i = 0; i < cut; ++i) if (r2->signal(i) != sigs[i]) ++totalDiff;
                    if (isExpr) totalSer += static_cast<ExprRule*>(r2.get())->series_diff(*static_cast<ExprRule*>(rule.get()), cut);
                }
                printf("[%s] SELFTEST причинности (8 точек среза): расхождений сигналов %d, расхождений рядов индикаторов %d -> %s\n", id.c_str(), totalDiff, totalSer, (totalDiff + totalSer) == 0 ? "OK" : "ЕСТЬ ЗАГЛЯДЫВАНИЕ");
                if (totalDiff + totalSer) { exitCode = 4; if (exam) { printf("[%s] экзамен не открыт: проверка причинности не пройдена\n", id.c_str()); continue; } }
            }

            printf("\n[%s] %s %s  параметры: %s\n", id.c_str(), pair.c_str(), tf.c_str(), over.empty() ? "по умолчанию" : over.c_str());
            bool devOk = false;
            std::string js = report(id, over, "dev", wDev, b, tr, sigs, devOk);
            if (isStrat) {
                printf("  отбор: %s\n", lt.ftext.c_str());
                js.insert(js.rfind("\"verdict\""), "\"funnel\":" + lt.fjson + ",\n   ");
            }
            devRules += (devRules.empty() ? "" : ",\n") + js;

            if (!exam) continue;
            if (isSig) { printf("[%s] экзамен не открыт: для сигналов модели он не запрограммирован\n", id.c_str()); exitCode = 5; continue; }
            if (role != "primary") { printf("[%s] экзамен не открыт: он только для основных тестов (role=primary)\n", id.c_str()); exitCode = 5; continue; }
            if (!devOk) { printf("[%s] экзамен не открыт: разработка не пройдена\n", id.c_str()); exitCode = 5; continue; }
            if (wExam.empty()) { printf("[%s] экзамен не открыт: нет данных\n", id.c_str()); exitCode = 5; continue; }
            // версия правила = все значения параметров, выходы, издержки и схема окон
            std::string ver; for (const auto& kv : P) ver += kv.first + "=" + num_s(kv.second) + ";";
            ver += "hold=" + std::to_string(X.hold) + ";stop=" + num_s(X.stopMult) + ";atr=" + std::to_string(X.atrP) + ";"; ver += "comm=" + num_s(cs.at("commission_per_lot_usd").num(7)) + ";wf=" + std::to_string(PL.train) + "+" + std::to_string(PL.test) + ";";
            if (isExpr) { for (const char* k : {"entry_long_expr", "entry_short_expr"}) if (rj.has(k)) ver += rj.at(k).str() + ";"; }
            for (auto& ch : ver) if (ch == '|' || ch == '\n') ch = ' ';
            const std::string logPath = regDir + "exam_log.txt", key = "|" + id + "|";
            std::string blocked; {
                std::ifstream lf(logPath); std::string line;
                while (std::getline(lf, line)) {
                    if (!line.empty() && line.back() == '\r') line.pop_back();
                    if (line.find(key) == std::string::npos) continue;
                    if (line.find(key + pair + "|" + tf + "|") != std::string::npos) blocked = "для этого правила, инструмента и таймфрейма он уже открывался";
                    else if (line.substr(line.rfind('|') + 1) != ver) blocked = "это правило уже сдавало экзамен в другой редакции (нужен новый ID, экзамен для него не чистый)";
                }
            }
            if (!blocked.empty()) { printf("[%s] экзамен не открыт: %s\n", id.c_str(), blocked.c_str()); exitCode = 5; continue; }
            {   // запись об открытии делается до расчёта
                std::ofstream lf(logPath, std::ios::app);
                lf << ymd((int64_t)time(nullptr)) << key << pair << "|" << tf << "|" << testName << "|" << ver << "\n"; lf.flush();
                if (!lf) throw std::runtime_error("не записать журнал экзамена: " + logPath);
            }
            Bars be = full; cut_bars(be, examCut);
            BarCache ce; ce.dir = bdir; ce.pair = pair; ce.cutoff = examCut;
            std::vector<int> se; std::vector<Trade> te; Strat le;
            if (isStrat) {
                le = run_strategy(id, P, be, ce.get("H1"), ce, first_at(be, wExam.front().t0), X.comm, X.comm_by_price);
                se = le.sigs; te = strat_trades(le, be);
            } else {
                std::unique_ptr<IRule> re;
                if (isExpr) re.reset(new ExprRule(rj, P, be, ce, catalog)); else { re = fac[id](); re->init(P, be); }
                std::vector<double> Ae = atr(be, X.atrP);
                te = simulate(*re, be, Ae, first_at(be, wExam.front().t0), X, &se);
            }
            bool exOk = false;
            std::string ej = report(id, over, "exam", wExam, be, te, se, exOk);
            if (isStrat) ej.insert(ej.rfind("\"verdict\""), "\"funnel\":" + le.fjson + ",\n   ");
            examRules += (examRules.empty() ? "" : ",\n") + ej; ++examDone;
        }
        auto save = [&](const std::string& mode, const Bars& bb, const std::string& rules, const std::string& outPath) {
            std::string out = "{\n \"mode\":\"" + mode + "\",\n" + head + " \"bars\":" + std::to_string(bb.size()) + ", \"history\":\"" + ymd(bb.t.front()) + " .. " + ymd(bb.t.back()) + "\",\n" + costs + " \"rules\":[\n" + rules + "\n ]\n}\n";
            FILE* f = fopen(outPath.c_str(), "wb");
            if (!f) throw std::runtime_error("не записать результат: " + outPath);
            fwrite(out.data(), 1, out.size(), f); fclose(f); printf("\nРезультат записан: %s\n", outPath.c_str());
        };
        std::string outPath = cfg.has("output") ? cfg.at("output").str() : dir + "../results/" + testName + ".json";
        save("dev", b, devRules, outPath);
        if (examDone) { Bars be = full; cut_bars(be, examCut); size_t dot = outPath.rfind(".json"); save("exam", be, examRules, outPath.substr(0, dot) + "_exam.json"); }
        return exitCode;
    } catch (const std::exception& e) { std::cerr << "ОШИБКА: " << e.what() << "\n"; return 1; }
}
