#include <cmath>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <map>
#include <omp.h>
static const int NUM_QFEATS = 23;
static const int NUM_FLAGS  = 9;
#pragma pack(push, 1)
struct V3SliceEntry {
    char timeframe[8];
    uint64_t start_row;
    uint32_t num_rows;
};
struct V3QuantHeader {
    char magic[8];
    uint32_t num_slices;
    uint32_t num_qfeats;
    uint32_t num_flags;
    uint64_t total_rows;
    uint64_t index_offset;
    float bin_edges[NUM_QFEATS][256];
};
struct TickFileHeader {
    char magic[8];
    float point;
    uint32_t num_days;
    uint64_t total_ticks;
};
struct TickDayIndex {
    uint32_t day_ts;
    uint64_t start_tick_idx;
    uint32_t num_ticks;
};
struct TickRecord {
    uint32_t ts_sec;
    float bid;
    uint16_t spread_pts;
};
#pragma pack(pop)
struct Signal {
    uint32_t bar_close_utc;
    int sym_id;
    int dir;
    float atr14;
    uint8_t hit_trr;
};
struct UtcParts {
    int year, month, day, hour, wday;
};
UtcParts parse_utc(uint32_t ts) {
    uint32_t days = ts / 86400U;
    uint32_t rem  = ts % 86400U;
    int hour = (int)(rem / 3600U);
    int wday = (int)((days + 4U) % 7U);
    int64_t z = (int64_t)days + 719468;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    uint32_t doe = (uint32_t)(z - era * 146097);
    uint32_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t y = (int64_t)yoe + era * 400;
    uint32_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    uint32_t mp = (5 * doy + 2) / 153;
    int day = (int)(doy - (153 * mp + 2) / 5 + 1);
    int month = (int)(mp < 10 ? mp + 3 : mp - 9);
    int year = (int)(y + (month <= 2 ? 1 : 0));
    return {year, month, day, hour, wday};
}
int get_broker_offset_sec(uint32_t utc_ts) {
    UtcParts g = parse_utc(utc_ts);
    if (g.month > 3 && g.month < 10) return 10800;
    if (g.month == 3) {
        int last_sun = 31 - ((g.wday + 31 - g.day) % 7);
        if (g.day > last_sun || (g.day == last_sun && g.hour >= 1)) return 10800;
    }
    if (g.month == 10) {
        int last_sun = 31 - ((g.wday + 31 - g.day) % 7);
        if (g.day < last_sun || (g.day == last_sun && g.hour < 1)) return 10800;
    }
    return 7200;
}
int get_broker_hour(uint32_t utc_ts) {
    int off_h = get_broker_offset_sec(utc_ts) / 3600;
    UtcParts g = parse_utc(utc_ts);
    return (g.hour + off_h) % 24;
}
uint32_t trading_elapsed_sec(uint32_t start_ts, uint32_t cur_ts) {
    if (cur_ts <= start_ts) return 0;
    uint32_t raw = cur_ts - start_ts;
    const uint32_t SAT_EPOCH = 172800U;
    const uint32_t WEEK_SEC  = 604800U;
    const uint32_t WKND_SEC  = 172800U;
    if (start_ts < SAT_EPOCH) return raw;
    uint32_t w_start = (start_ts - SAT_EPOCH) / WEEK_SEC;
    uint32_t w_cur   = (cur_ts   - SAT_EPOCH) / WEEK_SEC;
    uint32_t weekends = (w_cur > w_start) ? (w_cur - w_start) : 0;
    uint32_t sub = weekends * WKND_SEC;
    return (raw > sub) ? (raw - sub) : 0;
}
inline float mid_atr(const V3QuantHeader& qhdr, uint8_t bin) {
    if (bin >= 255) return qhdr.bin_edges[17][255];
    return 0.5f * (qhdr.bin_edges[17][bin] + qhdr.bin_edges[17][bin + 1]);
}
inline float val_of(const V3QuantHeader& qhdr, int feat, uint8_t bin) {
    return qhdr.bin_edges[feat][bin];
}
int main() {
    auto t0 = std::chrono::high_resolution_clock::now();
    std::ifstream tf("data/cache/EURUSD_ticks.bin", std::ios::binary);
    if (!tf) { std::cerr << "Cannot open EURUSD_ticks.bin\n"; return 1; }
    TickFileHeader thdr{};
    tf.read(reinterpret_cast<char*>(&thdr), sizeof(thdr));
    tf.seekg(sizeof(TickFileHeader) + thdr.num_days * sizeof(TickDayIndex));
    std::vector<TickRecord> ticks(thdr.total_ticks);
    tf.read(reinterpret_cast<char*>(ticks.data()), thdr.total_ticks * sizeof(TickRecord));
    tf.close();
    std::ifstream qf("data/cache/v3_quant_HTF.bin", std::ios::binary);
    if (!qf) { std::cerr << "Cannot open v3_quant_HTF.bin\n"; return 1; }
    V3QuantHeader qhdr{};
    qf.read(reinterpret_cast<char*>(&qhdr), sizeof(qhdr));
    qf.seekg(qhdr.index_offset);
    std::vector<V3SliceEntry> slices(qhdr.num_slices);
    qf.read(reinterpret_cast<char*>(slices.data()), qhdr.num_slices * sizeof(V3SliceEntry));
    uint64_t N = qhdr.total_rows;
    uint64_t base_sym  = sizeof(V3QuantHeader);
    uint64_t base_time = base_sym + N;
    uint64_t base_q    = base_time + N * 4ULL;
    uint64_t base_flg  = base_q + NUM_QFEATS * N;
    uint64_t base_tup  = base_flg + NUM_FLAGS * N;
    uint64_t base_trr  = base_tup + N;
    std::ofstream out("rules/tick_opt_results.txt");
    auto log = [&](const std::string& line) {
        std::cout << line << "\n";
        out << line << "\n";
    };
    log("==========================================================================================");
    log("  ПОИСК РЕАЛЬНОГО ПЕРЕВЕСА V3: MEAN-REVERSION + БЕЗУБЫТОК НА ТИКАХ DUKASCOPY И 6 ПАРАХ");
    log("==========================================================================================");
    // Проверяем все таймфреймы в v3_quant_HTF.bin (H1, H4, D1)
    for (const auto& s : slices) {
        std::string tf_name(s.timeframe);
        uint64_t st = s.start_row;
        uint32_t M  = s.num_rows;
        int tf_h = (tf_name == "D1") ? 24 : ((tf_name == "H4") ? 4 : 1);
        std::vector<uint8_t> sym(M), tup(M), trr(M);
        std::vector<uint32_t> ts(M);
        std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M));
        std::vector<std::vector<int8_t>> flg(NUM_FLAGS, std::vector<int8_t>(M));
        qf.seekg(base_sym + st);      qf.read((char*)sym.data(), M);
        qf.seekg(base_time + st * 4); qf.read((char*)ts.data(), M * 4);
        for (int f = 0; f < NUM_QFEATS; ++f) {
            qf.seekg(base_q + f * N + st);
            qf.read((char*)q[f].data(), M);
        }
        for (int g = 0; g < NUM_FLAGS; ++g) {
            qf.seekg(base_flg + g * N + st);
            qf.read((char*)flg[g].data(), M);
        }
        qf.seekg(base_tup + st); qf.read((char*)tup.data(), M);
        qf.seekg(base_trr + st); qf.read((char*)trr.data(), M);
        log("\n--- ТАЙМФРЕЙМ: " + tf_name + " (Строк=" + std::to_string(M) + ") ---");
        // Тестируем 4 непереобучаемых архетипа (2020-2026) по Target_RR (SL=1.5 ATR, TP=2.0 ATR)
        struct Arch { std::string name; int id; };
        std::vector<Arch> archs = {
            {"1. Возврат из перекупленности/перепроданности (RSI5 экстремум + CCI8 разворот)", 1},
            {"2. Отбой от границы канала во флэте (Triple==0 + Wick_Reject>=0.50)", 2},
            {"3. Сильный разворотный паттерн Беляева (FigureID==20 или Ratio_L>=1.8 + Wick>=0.4)", 3},
            {"4. Контртрендовый сквиз (Price_vs_HTF_EMA21 экстремум + MACD_Delta разворот)", 4}
        };
        for (const auto& a : archs) {
            int tot = 0, wins = 0;
            std::vector<Signal> eu_sigs;
            std::vector<Signal> port_sigs;
            for (uint32_t i = 0; i < M; ++i) {
                if (ts[i] < 1577836800U) continue;
                float ratio_l = val_of(qhdr, 2,  q[2][i]);
                float ema5_8  = val_of(qhdr, 3,  q[3][i]);
                float macd_d  = val_of(qhdr, 6,  q[6][i]);
                float rsi5    = val_of(qhdr, 9,  q[9][i]);
                float cci8    = val_of(qhdr, 12, q[12][i]);
                float fig     = val_of(qhdr, 15, q[15][i]);
                float pen     = val_of(qhdr, 16, q[16][i]);
                float p_htf   = val_of(qhdr, 20, q[20][i]);
                float wick    = val_of(qhdr, 22, q[22][i]);
                int triple    = flg[8][i];
                int eta_dir = (ema5_8 >= 0.0f) ? 1 : -1;
                bool match = false;
                if (a.id == 1) {
                    // Вход по направлению разворота (eta_dir), когда RSI5 и CCI8 выходят из экстремума
                    if (eta_dir == 1 && rsi5 <= 30.0f && cci8 <= -100.0f) match = true;
                    if (eta_dir == -1 && rsi5 >= 70.0f && cci8 >= 100.0f) match = true;
                } else if (a.id == 2) {
                    if (triple == 0 && wick >= 0.50f && pen <= 1.0f) match = true;
                } else if (a.id == 3) {
                    if ((int)std::round(fig) == 20 || (ratio_l >= 1.8f && wick >= 0.40f && pen <= 1.0f)) match = true;
                } else if (a.id == 4) {
                    if (eta_dir == 1 && p_htf <= -1.2f && macd_d > 0.0f) match = true;
                    if (eta_dir == -1 && p_htf >= 1.2f && macd_d < 0.0f) match = true;
                }
                if (match) {
                    tot++;
                    if (trr[i] == 1) wins++;
                    uint32_t close_brk = ts[i] + tf_h * 3600U;
                    uint32_t close_utc = close_brk - get_broker_offset_sec(close_brk - 7200U);
                    Signal sig{close_utc, sym[i], eta_dir, mid_atr(qhdr, q[17][i]), trr[i]};
                    port_sigs.push_back(sig);
                    if (sym[i] == 1) eu_sigs.push_back(sig);
                }
            }
            double wr = tot > 0 ? (100.0 * wins / tot) : 0.0;
            double pf_est = (wr / 100.0 * 1.25) / std::max(0.01, (1.0 - wr / 100.0) * 1.08);
            char buf[180];
            std::snprintf(buf, sizeof(buf), "  %-78s | N=%4d | WR=%5.1f%% | PF=%4.2f",
                          a.name.c_str(), tot, wr, pf_est);
            log(buf);
            // Если это H4 и стратегия перспективна (или это модель 2/3/4), прогоняем на 41.7 млн тиков EURUSD с безубытком!
            if (tf_name == "H4" && !eu_sigs.empty()) {
                std::sort(eu_sigs.begin(), eu_sigs.end(), [](const Signal& x, const Signal& y) {
                    return x.bar_close_utc < y.bar_close_utc;
                });
                for (bool use_be : {false, true}) {
                    double bal = 1000.0, peak = 1000.0, max_dd = 0.0, gp = 0.0, gl = 0.0;
                    int tr = 0, w = 0;
                    uint32_t busy = 0;
                    for (const auto& sg : eu_sigs) {
                        if (sg.bar_close_utc < busy) continue;
                        int bh = get_broker_hour(sg.bar_close_utc);
                        if (bh == 23 || bh == 0 || bh == 1) continue;
                        auto it = std::lower_bound(ticks.begin(), ticks.end(), sg.bar_close_utc,
                            [](const TickRecord& trk, uint32_t t) { return trk.ts_sec < t; });
                        if (it == ticks.end() || it->ts_sec - sg.bar_close_utc > 60) continue;
                        if (it->spread_pts > 25) continue;
                        double sp = it->spread_pts * 1e-5;
                        double sl_d = std::max(0.0005, (double)sg.atr14 * 2.0);
                        double tp_d = std::max(0.0007, (double)sg.atr14 * 2.6);
                        double be_trig = (double)sg.atr14 * 1.1; // перевод в безубыток при +1.1 ATR
                        double entry = (sg.dir == 1) ? (it->bid + sp) : it->bid;
                        double sl_p  = (sg.dir == 1) ? (entry - sl_d) : (entry + sl_d);
                        double tp_p  = (sg.dir == 1) ? (entry + tp_d) : (entry - tp_d);
                        double exit_p = entry;
                        uint32_t close_t = it->ts_sec;
                        bool closed = false;
                        for (auto cur = it + 1; cur != ticks.end(); ++cur) {
                            double csp = cur->spread_pts * 1e-5;
                            if (trading_elapsed_sec(it->ts_sec, cur->ts_sec) >= 4U * 50U * 3600U) {
                                exit_p = (sg.dir == 1) ? cur->bid : (cur->bid + csp);
                                close_t = cur->ts_sec; closed = true; break;
                            }
                            if (sg.dir == 1) {
                                if (use_be && cur->bid >= entry + be_trig && sl_p < entry) sl_p = entry + 0.00005;
                                if (cur->bid <= sl_p) { exit_p = sl_p; close_t = cur->ts_sec; closed = true; break; }
                                if (cur->bid >= tp_p) { exit_p = tp_p; close_t = cur->ts_sec; closed = true; break; }
                            } else {
                                double ask = cur->bid + csp;
                                if (use_be && ask <= entry - be_trig && sl_p > entry) sl_p = entry - 0.00005;
                                if (ask >= sl_p) { exit_p = sl_p; close_t = cur->ts_sec; closed = true; break; }
                                if (ask <= tp_p) { exit_p = tp_p; close_t = cur->ts_sec; closed = true; break; }
                            }
                        }
                        if (!closed) continue;
                        busy = close_t;
                        double r_mult = (sg.dir == 1) ? ((exit_p - entry) / sl_d) : ((entry - exit_p) / sl_d);
                        double pnl = (bal * 0.01) * r_mult;
                        bal += pnl; tr++;
                        if (pnl > 0) { w++; gp += pnl; } else { gl += std::abs(pnl); }
                        if (bal > peak) peak = bal;
                        double dd = (peak - bal) / peak * 100.0;
                        if (dd > max_dd) max_dd = dd;
                    }
                    if (tr > 0) {
                        char tbuf[160];
                        std::snprintf(tbuf, sizeof(tbuf),
                            "     -> EURUSD ТИКИ (%s): Сделок=%2d | WR=%5.1f%% | PF=%4.2f | Баланс=$%8.2f | MaxDD=%5.2f%%",
                            use_be ? "С БЕЗУБЫТКОМ +1.1 ATR" : "БЕЗ БЕЗУБЫТКА       ",
                            tr, 100.0 * w / tr, gl > 0 ? (gp / gl) : 0.0, bal, max_dd);
                        log(tbuf);
                    }
                }
            }
        }
    }
    auto t1 = std::chrono::high_resolution_clock::now();
    log("\nВремя расчёта в облаке: " + std::to_string(std::chrono::duration<double>(t1 - t0).count()).substr(0, 5) + " сек.");
    return 0;
}
