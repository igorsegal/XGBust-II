// expr_rule.h - правило, заданное в реестре строкой условия и списком inputs (индикаторы), без кода на C++.
// Запись правила: inputs[{name, indicator, output?, tf?, source?, params{имя: число или "$параметр_правила"}}],
// entry_long_expr / entry_short_expr - строки условий. Условие вычисляется на закрытии каждого бара базового таймфрейма.
// Индикаторы старшего таймфрейма берутся по последнему ЗАКРЫТОМУ бару этого таймфрейма на момент закрытия базового бара.
#pragma once
#include "indicators.h"
#include "json_mini.h"
#include <set>
#include <functional>
#include <cctype>

// Кэш баров по таймфреймам (для старших таймфреймов).
struct BarCache {
    std::string dir, pair; std::map<std::string, Bars> m;
    int64_t cutoff = INT64_MAX;   // бары, закрывающиеся позже этого момента, не загружаются (разработка не видит экзамен)
    const Bars& get(const std::string& tf) {
        auto it = m.find(tf); if (it != m.end()) return it->second;
        char sep = dir.find('\\') != std::string::npos ? '\\' : '/';
        Bars b = load_xfbar(dir + sep + pair + sep + pair + "_" + tf + ".bin");
        cut_bars(b, cutoff);
        return m[tf] = std::move(b);
    }
};

// Выравнивание ряда старшего таймфрейма на бары базового: на баре i берём последний бар j старшего ТФ,
// закрытый к моменту закрытия бара i (t_htf[j] + период_htf <= t_base[i] + период_base).
inline Vec align_htf(const Bars& base, const Bars& htf, const Vec& v) {
    Vec o(base.size(), NaNv); size_t j = 0; bool any = false; size_t last = 0;
    for (size_t i = 0; i < base.size(); ++i) {
        int64_t close_t = base.t[i] + base.period_sec;
        while (j < htf.size() && htf.t[j] + htf.period_sec <= close_t) { last = j; any = true; ++j; }
        if (any) o[i] = v[last];
    }
    return o;
}

struct XNode {
    enum K { NUM, SER, FN, OP, NOT_, NEG } k = NUM;
    double v = 0; int ser = -1; std::string op; std::vector<std::unique_ptr<XNode>> kid;
};

class ExprRule : public IRule {
    std::vector<Vec> S; std::map<std::string, int> sname;   // ряды: цены и входы
    std::unique_ptr<XNode> eL, eS; std::set<int> used; int warm = 0;
    // ---- разбор ----
    struct Tok { enum T { NUM, ID, SYM, END } t; std::string s; double v; };
    std::vector<Tok> tk; size_t tp = 0; const Params* prm = nullptr;
    void lex(const std::string& s) {
        tk.clear(); tp = 0; size_t i = 0;
        while (i < s.size()) {
            char c = s[i];
            if (isspace((unsigned char)c)) { ++i; continue; }
            if (isdigit((unsigned char)c) || (c == '.' && i + 1 < s.size() && isdigit((unsigned char)s[i + 1]))) {
                char* e; double v = strtod(s.c_str() + i, &e); tk.push_back({Tok::NUM, "", v}); i = e - s.c_str(); continue;
            }
            if (isalpha((unsigned char)c) || c == '_') {
                size_t j = i; while (j < s.size() && (isalnum((unsigned char)s[j]) || s[j] == '_')) ++j;
                tk.push_back({Tok::ID, s.substr(i, j - i), 0}); i = j; continue;
            }
            std::string two = s.substr(i, 2);
            if (two == "<=" || two == ">=" || two == "==" || two == "!=") { tk.push_back({Tok::SYM, two, 0}); i += 2; continue; }
            if (std::string("<>+-*/(),").find(c) != std::string::npos) { tk.push_back({Tok::SYM, std::string(1, c), 0}); ++i; continue; }
            throw std::runtime_error(std::string("в условии недопустимый символ '") + c + "'");
        }
        tk.push_back({Tok::END, "", 0});
    }
    static std::string up(std::string s) { for (auto& c : s) c = (char)toupper((unsigned char)c); return s; }
    bool isSym(const char* s) { return tk[tp].t == Tok::SYM && tk[tp].s == s; }
    bool isKw(const char* s) { return tk[tp].t == Tok::ID && up(tk[tp].s) == s; }
    std::unique_ptr<XNode> mk(XNode::K k) { auto n = std::make_unique<XNode>(); n->k = k; return n; }
    std::unique_ptr<XNode> pOr() {
        auto l = pAnd();
        while (isKw("OR")) { ++tp; auto n = mk(XNode::OP); n->op = "OR"; n->kid.push_back(std::move(l)); n->kid.push_back(pAnd()); l = std::move(n); }
        return l;
    }
    std::unique_ptr<XNode> pAnd() {
        auto l = pNot();
        while (isKw("AND")) { ++tp; auto n = mk(XNode::OP); n->op = "AND"; n->kid.push_back(std::move(l)); n->kid.push_back(pNot()); l = std::move(n); }
        return l;
    }
    std::unique_ptr<XNode> pNot() {
        if (isKw("NOT")) { ++tp; auto n = mk(XNode::NOT_); n->kid.push_back(pNot()); return n; }
        return pCmp();
    }
    std::unique_ptr<XNode> pCmp() {
        auto l = pAdd();
        for (const char* o : {"<=", ">=", "==", "!=", "<", ">"}) if (isSym(o)) {
            ++tp; auto n = mk(XNode::OP); n->op = o; n->kid.push_back(std::move(l)); n->kid.push_back(pAdd());
            if (isSym("<") || isSym(">") || isSym("<=") || isSym(">=") || isSym("==") || isSym("!="))
                throw std::runtime_error("цепочки сравнений (a < b < c) не поддерживаются: используйте AND");
            return n;
        }
        return l;
    }
    std::unique_ptr<XNode> pAdd() {
        auto l = pMul();
        while (isSym("+") || isSym("-")) { std::string o = tk[tp++].s; auto n = mk(XNode::OP); n->op = o; n->kid.push_back(std::move(l)); n->kid.push_back(pMul()); l = std::move(n); }
        return l;
    }
    std::unique_ptr<XNode> pMul() {
        auto l = pUn();
        while (isSym("*") || isSym("/")) { std::string o = tk[tp++].s; auto n = mk(XNode::OP); n->op = o; n->kid.push_back(std::move(l)); n->kid.push_back(pUn()); l = std::move(n); }
        return l;
    }
    std::unique_ptr<XNode> pUn() {
        if (isSym("-")) { ++tp; auto n = mk(XNode::NEG); n->kid.push_back(pUn()); return n; }
        return pPrim();
    }
    std::unique_ptr<XNode> pPrim() {
        Tok t = tk[tp];
        if (t.t == Tok::NUM) { ++tp; auto n = mk(XNode::NUM); n->v = t.v; return n; }
        if (isSym("(")) { ++tp; auto e = pOr(); if (!isSym(")")) throw std::runtime_error("нет закрывающей скобки"); ++tp; return e; }
        if (t.t == Tok::ID) {
            ++tp; std::string nm = t.s;
            if (isSym("(")) {
                ++tp; auto n = mk(XNode::FN); n->op = nm;
                if (!isSym(")")) { while (true) { n->kid.push_back(pOr()); if (isSym(",")) { ++tp; continue; } break; } }
                if (!isSym(")")) throw std::runtime_error("нет закрывающей скобки у функции " + nm);
                ++tp;
                size_t need = (nm == "abs") ? 1 : (nm == "min" || nm == "max" || nm == "prev" || nm == "crossup" || nm == "crossdown") ? 2 : 99;
                if (need == 99) throw std::runtime_error("неизвестная функция: " + nm);
                if (n->kid.size() != need) throw std::runtime_error("функция " + nm + ": неверное число аргументов");
                if (nm == "prev") {
                    if (n->kid[1]->k != XNode::NUM || n->kid[1]->v < 0 || n->kid[1]->v != std::floor(n->kid[1]->v) || n->kid[1]->v > 5000)
                        throw std::runtime_error("prev(x, n): n должно быть целым числом от 0 до 5000");
                }
                return n;
            }
            if (up(nm) == "AND" || up(nm) == "OR" || up(nm) == "NOT") throw std::runtime_error("неожиданное слово " + nm);
            auto pi = prm->find(nm);
            if (pi != prm->end()) { auto n = mk(XNode::NUM); n->v = pi->second; return n; }
            auto si = sname.find(nm);
            if (si == sname.end()) throw std::runtime_error("в условии неизвестное имя: " + nm);
            auto n = mk(XNode::SER); n->ser = si->second; used.insert(si->second); return n;
        }
        throw std::runtime_error("ошибка в условии: ожидалось число, имя или скобка");
    }
    std::unique_ptr<XNode> parse(const std::string& s) {
        lex(s); auto r = pOr();
        if (tk[tp].t != Tok::END) throw std::runtime_error("лишнее в конце условия: " + tk[tp].s);
        return r;
    }
    // ---- вычисление (NaN = «неизвестно»; сравнения и логика с NaN дают NaN) ----
    double ev(const XNode* n, int i) const {
        switch (n->k) {
            case XNode::NUM: return n->v;
            case XNode::SER: return i >= 0 ? S[n->ser][i] : NaNv;
            case XNode::NEG: return -ev(n->kid[0].get(), i);
            case XNode::NOT_: { double a = ev(n->kid[0].get(), i); return std::isnan(a) ? NaNv : (a != 0 ? 0.0 : 1.0); }
            case XNode::FN: {
                const std::string& f = n->op;
                if (f == "abs") return std::fabs(ev(n->kid[0].get(), i));
                if (f == "min") return std::min(ev(n->kid[0].get(), i), ev(n->kid[1].get(), i));
                if (f == "max") return std::max(ev(n->kid[0].get(), i), ev(n->kid[1].get(), i));
                if (f == "prev") return i - (int)n->kid[1]->v >= 0 ? ev(n->kid[0].get(), i - (int)n->kid[1]->v) : NaNv;
                double a1 = ev(n->kid[0].get(), i), b1 = ev(n->kid[1].get(), i), a0 = ev(n->kid[0].get(), i - 1), b0 = ev(n->kid[1].get(), i - 1);
                if (std::isnan(a1) || std::isnan(b1) || std::isnan(a0) || std::isnan(b0)) return NaNv;
                if (f == "crossup") return (a1 > b1 && a0 <= b0) ? 1.0 : 0.0;
                return (a1 < b1 && a0 >= b0) ? 1.0 : 0.0;   // crossdown
            }
            case XNode::OP: {
                double a = ev(n->kid[0].get(), i), b = ev(n->kid[1].get(), i); const std::string& o = n->op;
                if (o == "AND") { if ((!std::isnan(a) && a == 0) || (!std::isnan(b) && b == 0)) return 0.0; return (std::isnan(a) || std::isnan(b)) ? NaNv : 1.0; }
                if (o == "OR") { if ((!std::isnan(a) && a != 0) || (!std::isnan(b) && b != 0)) return 1.0; return (std::isnan(a) || std::isnan(b)) ? NaNv : 0.0; }
                if (std::isnan(a) || std::isnan(b)) return NaNv;
                if (o == "+") return a + b;
                if (o == "-") return a - b;
                if (o == "*") return a * b;
                if (o == "/") return b == 0 ? NaNv : a / b;
                if (o == "<") return a < b;
                if (o == "<=") return a <= b;
                if (o == ">") return a > b;
                if (o == ">=") return a >= b;
                if (o == "==") return a == b;
                return a != b;
            }
        }
        return NaNv;
    }
    static bool truthy(double v) { return !std::isnan(v) && v != 0; }
public:
    // spec - запись правила из реестра; P - параметры правила (значения по умолчанию + переопределения конфига).
    ExprRule(const JV& spec, const Params& P, const Bars& base, BarCache& cache, const std::map<std::string, JV>& catalog) {
        prm = &P; size_t n = base.size();
        const char* pf[] = {"open", "high", "low", "close", "spread"};
        for (int k = 0; k < 5; ++k) {
            Vec v(n); for (size_t i = 0; i < n; ++i) v[i] = k == 0 ? base.o[i] : k == 1 ? base.h[i] : k == 2 ? base.l[i] : k == 3 ? base.c[i] : (double)base.spread[i];
            sname[pf[k]] = (int)S.size(); S.push_back(std::move(v));
        }
        std::string baseTf = tf_name(base.period_sec);
        if (spec.has("inputs")) for (const auto& in : spec.at("inputs").a) {
            std::string nm = in.at("name").str(), ind = in.at("indicator").str();
            if (sname.count(nm) || P.count(nm)) throw std::runtime_error("имя входа повторяется или совпадает с параметром/ценой: " + nm);
            if (!catalog.count(ind)) throw std::runtime_error("индикатора нет в справочнике: " + ind);
            const JV& cd = catalog.at(ind);
            if (cd.at("status").str() != "implemented") throw std::runtime_error("индикатор не реализован: " + ind);
            Params ap;
            for (const auto& kv : cd.at("params").o) ap[kv.first] = kv.second.at("default").num(0);
            if (in.has("params")) for (const auto& kv : in.at("params").o) {
                if (!cd.at("params").has(kv.first)) throw std::runtime_error(ind + ": нет параметра " + kv.first);
                double v;
                if (kv.second.t == JV::STR) {
                    if (kv.second.s.empty() || kv.second.s[0] != '$') throw std::runtime_error("строковое значение параметра должно быть ссылкой вида $имя");
                    auto pi = P.find(kv.second.s.substr(1));
                    if (pi == P.end()) throw std::runtime_error("ссылка на неизвестный параметр правила: " + kv.second.s);
                    v = pi->second;
                } else v = kv.second.num(0);
                const JV& pd = cd.at("params").at(kv.first);
                if (v < pd.at("min").num(-1e300) || v > pd.at("max").num(1e300)) throw std::runtime_error(ind + "." + kv.first + " вне диапазона справочника");
                if (pd.at("type").str() == "int" && v != std::floor(v)) throw std::runtime_error(ind + "." + kv.first + " должен быть целым");
                ap[kv.first] = v;
            }
            std::string out = in.has("output") ? in.at("output").str() : cd.at("default_output").str();
            bool okOut = false; for (const auto& o : cd.at("outputs").a) if (o.str() == out) okOut = true;
            if (!okOut) throw std::runtime_error(ind + ": нет выхода " + out);
            std::string tf = in.has("tf") ? in.at("tf").str() : baseTf;
            std::string src = in.has("source") ? in.at("source").str() : "close";
            Vec series;
            if (tf == baseTf) series = compute_indicator(ind, ap, base, src)[out];
            else {
                const Bars& hb = cache.get(tf);
                if (hb.period_sec < base.period_sec) throw std::runtime_error("вход " + nm + ": таймфрейм " + tf + " младше базового " + baseTf);
                series = align_htf(base, hb, compute_indicator(ind, ap, hb, src)[out]);
            }
            sname[nm] = (int)S.size(); S.push_back(std::move(series));
        }
        if (spec.has("entry_long_expr") && !spec.at("entry_long_expr").str().empty()) eL = parse(spec.at("entry_long_expr").str());
        if (spec.has("entry_short_expr") && !spec.at("entry_short_expr").str().empty()) eS = parse(spec.at("entry_short_expr").str());
        if (!eL && !eS) throw std::runtime_error("у правила нет ни entry_long_expr, ни entry_short_expr");
    }
    static std::string tf_name(int sec) {
        switch (sec) { case 60: return "M1"; case 300: return "M5"; case 900: return "M15"; case 1800: return "M30"; case 3600: return "H1"; case 14400: return "H4"; case 86400: return "D1"; case 604800: return "W1"; }
        return "?" + std::to_string(sec);
    }
    // Для проверки причинности: сколько баров до upto имеют отличающееся значение хотя бы одного ряда (NaN равен NaN).
    int series_diff(const ExprRule& o, int upto) const {
        int d = 0;
        for (int i = 0; i < upto; ++i) {
            bool bad = false;
            for (size_t k = 0; k < S.size() && !bad; ++k) {
                double a = S[k][i], b = o.S[k][i];
                if (std::isnan(a) != std::isnan(b) || (!std::isnan(a) && std::fabs(a - b) > 1e-12 * std::max(1.0, std::fabs(a)))) bad = true;
            }
            if (bad) ++d;
        }
        return d;
    }
    void init(const Params&, const Bars&) override {}
    int warmup() const override { return warm; }
    int signal(int i) override {
        bool l = eL && truthy(ev(eL.get(), i)), s = eS && truthy(ev(eS.get(), i));
        if (l && s) return 0;   // противоречие: оба условия сразу - сигнала нет
        return l ? 1 : (s ? -1 : 0);
    }
};
