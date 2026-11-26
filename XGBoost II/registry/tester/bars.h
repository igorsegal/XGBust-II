// bars.h - чтение истории XFBAR001 и общий интерфейс правила.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <memory>
#include <stdexcept>
#include <cmath>
#include <climits>

struct Bars {
    std::string symbol;
    double point = 0.00001;
    int period_sec = 0;
    std::vector<int64_t> t;
    std::vector<double> o, h, l, c;
    std::vector<int32_t> spread;   // пункты
    std::vector<double> v;         // тиковый объём бара
    size_t size() const { return t.size(); }
};

#pragma pack(push, 1)
struct XfRec { int64_t time; double o, h, l, c; int64_t tv; int32_t spread; int64_t rv; };
#pragma pack(pop)
static_assert(sizeof(XfRec) == 60, "запись XFBAR должна быть 60 байт");

inline Bars load_xfbar(const std::string& path) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) throw std::runtime_error("не открыть файл баров: " + path);
    char magic[8]; int32_t ver, rs, per, dg; double pt; int64_t n, ft, lt; int32_t sl;
    if (fread(magic, 1, 8, f) != 8 || memcmp(magic, "XFBAR001", 8) != 0) { fclose(f); throw std::runtime_error("не XFBAR001: " + path); }
    bool ok = fread(&ver, 4, 1, f) == 1 && fread(&rs, 4, 1, f) == 1 && fread(&per, 4, 1, f) == 1 && fread(&dg, 4, 1, f) == 1 &&
              fread(&pt, 8, 1, f) == 1 && fread(&n, 8, 1, f) == 1 && fread(&ft, 8, 1, f) == 1 && fread(&lt, 8, 1, f) == 1 && fread(&sl, 4, 1, f) == 1;
    if (!ok || rs != 60 || sl < 0 || sl > 64) { fclose(f); throw std::runtime_error("битый заголовок: " + path); }
    std::string sym(sl, 0); if (sl && fread(&sym[0], 1, sl, f) != (size_t)sl) { fclose(f); throw std::runtime_error("обрыв имени символа"); }
    Bars b; b.symbol = sym; b.point = pt; b.period_sec = per;
    std::vector<XfRec> recs((size_t)n);
    size_t got = fread(recs.data(), sizeof(XfRec), (size_t)n, f); fclose(f);
    if (got != (size_t)n) throw std::runtime_error("файл короче заголовка: " + path);
    for (auto& r : recs) { b.t.push_back(r.time); b.o.push_back(r.o); b.h.push_back(r.h); b.l.push_back(r.l); b.c.push_back(r.c); b.spread.push_back(r.spread); b.v.push_back((double)r.tv); }
    for (size_t i = 1; i < b.size(); ++i) if (b.t[i] <= b.t[i - 1]) throw std::runtime_error("время баров не растёт: " + path);
    return b;
}

// Оставить только бары, закрывшиеся не позже cutoff.
inline void cut_bars(Bars& b, int64_t cutoff) {
    size_t n = b.size(); while (n && b.t[n - 1] + b.period_sec > cutoff) --n;
    b.t.resize(n); b.o.resize(n); b.h.resize(n); b.l.resize(n); b.c.resize(n); b.spread.resize(n); b.v.resize(n);
}

// Параметры правила: имя -> число (все параметры в реестре числовые или булевы).
typedef std::map<std::string, double> Params;

// Интерфейс правила. Сигнал bar i вычисляется ТОЛЬКО по барам 0..i (закрытие бара i).
struct IRule {
    virtual ~IRule() {}
    virtual void init(const Params& p, const Bars& bars) = 0;   // подготовка (только причинные расчёты)
    virtual int warmup() const = 0;                              // сколько баров нужно до первого сигнала
    virtual int signal(int i) = 0;                               // +1 лонг, -1 шорт, 0 нет; вызывается подряд для i = 0,1,2,...
};
typedef std::unique_ptr<IRule> (*RuleFactory)();
