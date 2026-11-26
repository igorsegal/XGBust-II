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
#include <ctime>
#include <map>
#include <deque>
#include <omp.h>
static const int NUM_QFEATS = 23;
static const int NUM_FLAGS  = 9;
inline bool is_scale_invariant(int feat_idx) {
    return feat_idx != 17; // Исключаем ненормированный ATR14
}
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
#pragma pack(pop)
struct Rule {
    int dir;         // 1 = BUY, -1 = SELL
    int trend_mode;  // 1, -1, 0
    int f1, f2;
    uint8_t b1, b2;
    bool gt1, gt2;
    double score;
};
struct TradeEvent {
    uint32_t time_sec;
    uint8_t sym_id;
    int dir;
    bool is_win;
};
struct YearStats {
    int trades = 0;
    int wins = 0;
    double gross_profit = 0.0;
    double gross_loss = 0.0;
    double net_usd = 0.0;
};
std::string fmt_date(uint32_t ts) {
    std::time_t t = static_cast<std::time_t>(ts);
    std::tm* tm_ptr = std::gmtime(&t);
    char buf[32];
    if (tm_ptr && std::strftime(buf, sizeof(buf), "%Y-%m-%d", tm_ptr)) return std::string(buf);
    return "1970-01-01";
}
int get_year(uint32_t ts) {
    std::time_t t = static_cast<std::time_t>(ts);
    std::tm* tm_ptr = std::gmtime(&t);
    return tm_ptr ? (tm_ptr->tm_year + 1900) : 1970;
}
int main(int argc, char** argv) {
    std::string target_tf = (argc > 1) ? argv[1] : "H4";
    std::string cache_path = "data/cache/v3_quant_HTF.bin";
    auto t0 = std::chrono::high_resolution_clock::now();
    std::ifstream in(cache_path, std::ios::binary);
    if (!in) return 1;
    V3QuantHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    in.seekg(hdr.index_offset);
    std::vector<V3SliceEntry> slices(hdr.num_slices);
    in.read(reinterpret_cast<char*>(slices.data()), hdr.num_slices * sizeof(V3SliceEntry));
    V3SliceEntry chosen{};
    bool found = false;
    for (const auto& s : slices) {
        if (std::string(s.timeframe) == target_tf) { chosen = s; found = true; break; }
    }
    if (!found) return 1;
    uint64_t N = hdr.total_rows;
    uint64_t st = chosen.start_row;
    uint32_t M  = chosen.num_rows;
    uint64_t base_sym  = sizeof(V3QuantHeader);
    uint64_t base_time = base_sym + N;
    uint64_t base_q    = base_time + N * 4ULL;
    uint64_t base_flg  = base_q + NUM_QFEATS * N;
    uint64_t base_tup  = base_flg + NUM_FLAGS * N;
    uint64_t base_trr  = base_tup + N;
    std::vector<uint8_t> sym(M);
    std::vector<uint32_t> ts(M);
    std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M));
    std::vector<int8_t> triple(M);
    std::vector<int8_t> heavy_conf(M);
    std::vector<uint8_t> tup(M), trr(M);
    in.seekg(base_sym + st);      in.read(reinterpret_cast<char*>(sym.data()), M);
    in.seekg(base_time + st * 4); in.read(reinterpret_cast<char*>(ts.data()), M * 4);
    for (int f = 0; f < NUM_QFEATS; ++f) {
        in.seekg(base_q + f * N + st);
        in.read(reinterpret_cast<char*>(q[f].data()), M);
    }
    in.seekg(base_flg + 6ULL * N + st); in.read(reinterpret_cast<char*>(heavy_conf.data()), M); // Heavy_Trend_Confirmed
    in.seekg(base_flg + 8ULL * N + st); in.read(reinterpret_cast<char*>(triple.data()), M);     // Triple_Trend_Align
    in.seekg(base_tup + st);            in.read(reinterpret_cast<char*>(tup.data()), M);
    in.seekg(base_trr + st);            in.read(reinterpret_cast<char*>(trr.data()), M);
    // Определяем список всех уникальных SymbolID в срезе
    uint8_t max_sym = 0;
    for (uint32_t i = 0; i < M; ++i) if (sym[i] > max_sym) max_sym = sym[i];
    int num_syms = max_sym + 1;
    const uint32_t SEC_9M = 274U * 86400U;
    const uint32_t SEC_3M = 91U * 86400U;
    uint32_t oos_start = 1577836800U; // 2020-01-01
    uint32_t max_ts = 0;
    for (uint32_t i = 0; i < M; ++i) if (ts[i] > max_ts) max_ts = ts[i];
    std::vector<TradeEvent> all_oos_trades;
    int window_num = 0;
    const int trend_modes[3] = {1, -1, 0};
    std::cout << "=== PER-SYMBOL WALK-FORWARD (" << target_tf << ", Symbols=" << num_syms << "): 9M Train -> 3M OOS ===\n";
    while (oos_start + 15 * 86400U < max_ts) {
        uint32_t train_start = oos_start - SEC_9M;
        uint32_t oos_end     = std::min(max_ts, oos_start + SEC_3M);
        window_num++;
        // Раскладываем индексы баров по каждому инструменту отдельно!
        std::vector<std::vector<uint32_t>> sym_tr(num_syms), sym_oos(num_syms);
        for (uint32_t i = 0; i < M; ++i) {
            if (ts[i] >= train_start && ts[i] < oos_start) sym_tr[sym[i]].push_back(i);
            else if (ts[i] >= oos_start && ts[i] < oos_end) sym_oos[sym[i]].push_back(i);
        }
        int q_trades = 0, q_wins = 0;
        double q_gp = 0.0, q_gl = 0.0;
        // Параллельно по инструментам: каждый инструмент учит СВОИ правила на своих 9 месяцах!
        #pragma omp parallel
        {
            std::vector<TradeEvent> local_trades;
            int l_tr = 0, l_w = 0;
            double l_gp = 0.0, l_gl = 0.0;
            #pragma omp for schedule(dynamic, 1)
            for (int s = 0; s < num_syms; ++s) {
                const auto& tr_idx  = sym_tr[s];
                const auto& oos_idx = sym_oos[s];
                if (tr_idx.size() < 200 || oos_idx.empty()) continue;
                std::vector<Rule> cand;
                for (int tm : trend_modes) {
                    for (int f1 = 0; f1 < NUM_QFEATS; ++f1) {
                        if (!is_scale_invariant(f1)) continue;
                        for (int f2 = f1 + 1; f2 < NUM_QFEATS; ++f2) {
                            if (!is_scale_invariant(f2)) continue;
                            for (int b1 = 48; b1 <= 208; b1 += 40) {
                                for (int b2 = 48; b2 <= 208; b2 += 40) {
                                    for (int gt1 = 0; gt1 <= 1; ++gt1) {
                                        for (int gt2 = 0; gt2 <= 1; ++gt2) {
                                            int n = 0, bw = 0, sw = 0;
                                            for (uint32_t idx : tr_idx) {
                                                if (tm != 0 && triple[idx] != tm) continue;
                                                bool c1 = gt1 ? (q[f1][idx] >= b1) : (q[f1][idx] <= b1);
                                                if (!c1) continue;
                                                bool c2 = gt2 ? (q[f2][idx] >= b2) : (q[f2][idx] <= b2);
                                                if (!c2) continue;
                                                n++;
                                                if (trr[idx] == 1) bw++;
                                                if (tup[idx] == 0) sw++;
                                            }
                                            if (n >= 22) {
                                                // Строгий порог отбора на 9 мес: Train PF >= 1.55
                                                double b_wr = (double)bw / n;
                                                double b_pf = (b_wr * 1.42) / std::max(0.01, 1.0 - b_wr);
                                                if (b_wr >= 0.52 && b_pf >= 1.55) {
                                                    cand.push_back({1, tm, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                    (b_pf - 1.0) * std::sqrt((double)n)});
                                                }
                                                double s_wr = (double)sw / n;
                                                double s_pf = (s_wr * 0.94) / std::max(0.01, 1.0 - s_wr);
                                                if (s_wr >= 0.62 && s_pf >= 1.55) {
                                                    cand.push_back({-1, tm, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                    (s_pf - 1.0) * std::sqrt((double)n)});
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                std::sort(cand.begin(), cand.end(), [](const Rule& a, const Rule& b) { return a.score > b.score; });
                std::vector<Rule> best_s;
                for (const auto& r : cand) {
                    bool dup = false;
                    for (const auto& b : best_s) {
                        if (b.dir == r.dir && (b.f1 == r.f1 || b.f2 == r.f2)) { dup = true; break; }
                    }
                    if (!dup) best_s.push_back(r);
                    if (best_s.size() >= 2) break; // Топ-2 самых сильных и независимых правила на инструмент
                }
                for (uint32_t idx : oos_idx) {
                    int sig = 0;
                    for (const auto& r : best_s) {
                        if (r.trend_mode != 0 && triple[idx] != r.trend_mode) continue;
                        bool c1 = r.gt1 ? (q[r.f1][idx] >= r.b1) : (q[r.f1][idx] <= r.b1);
                        if (!c1) continue;
                        bool c2 = r.gt2 ? (q[r.f2][idx] >= r.b2) : (q[r.f2][idx] <= r.b2);
                        if (!c2) continue;
                        sig = r.dir;
                        break;
                    }
                    if (sig != 0) {
                        bool win = (sig == 1) ? (trr[idx] == 1) : (tup[idx] == 0);
                        local_trades.push_back({ts[idx], (uint8_t)s, sig, win});
                        l_tr++;
                        if (win) { l_w++; l_gp += (sig == 1) ? 1.42 : 0.94; }
                        else     { l_gl += 1.00; }
                    }
                }
            }
            #pragma omp critical
            {
                all_oos_trades.insert(all_oos_trades.end(), local_trades.begin(), local_trades.end());
                q_trades += l_tr;
                q_wins   += l_w;
                q_gp     += l_gp;
                q_gl     += l_gl;
            }
        }
        double q_wr = (q_trades > 0) ? (100.0 * q_wins / q_trades) : 0.0;
        double q_pf = (q_gl > 0.0) ? (q_gp / q_gl) : (q_gp > 0.0 ? 99.0 : 0.0);
        std::cout << "Q" << std::setw(2) << std::setfill('0') << window_num << std::setfill(' ')
                  << " [" << fmt_date(oos_start) << " .. " << fmt_date(oos_end) << "]"
                  << " | Signals=" << std::setw(4) << q_trades
                  << " | WR=" << std::fixed << std::setprecision(1) << std::setw(5) << q_wr << "%"
                  << " | PF=" << std::setprecision(2) << q_pf << "\n";
        oos_start += SEC_3M;
    }
    std::sort(all_oos_trades.begin(), all_oos_trades.end(), [](const TradeEvent& a, const TradeEvent& b) {
        if (a.time_sec != b.time_sec) return a.time_sec < b.time_sec;
        return a.sym_id < b.sym_id;
    });
    std::vector<uint32_t> last_sym_ts(256, 0);
    std::vector<std::deque<double>> sym_hist(256); // История последних 12 сделок по символу для адаптивного риска
    std::map<int, YearStats> yearly;
    double balance = 1000.0;
    double peak = 1000.0;
    double max_dd_pct = 0.0;
    int total_trades = 0, wins = 0;
    double gross_profit = 0.0, gross_loss = 0.0;
    std::ofstream csv("rules/wf_equity_curve.csv");
    csv << "TradeNum,Timestamp,Date,SymbolID,Dir,Win,PnL_USD,Balance,DrawdownPct\n";
    csv << "0,1577836800,2020-01-01,0,INIT,1,0.00,1000.00,0.00\n";
    uint32_t first_ts = 0, last_ts = 0;
    for (const auto& ev : all_oos_trades) {
        if (ev.time_sec - last_sym_ts[ev.sym_id] < 14400) continue;
        last_sym_ts[ev.sym_id] = ev.time_sec;
        if (first_ts == 0) first_ts = ev.time_sec;
        last_ts = ev.time_sec;
        // Адаптивный риск: 1.0% базовый, но если по инструменту за последние 12 сделок PF < 1.0 -> режем риск до 0.25%
        double risk_pct = 0.01;
        const auto& h = sym_hist[ev.sym_id];
        if (h.size() >= 8) {
            double gp_h = 0.0, gl_h = 0.0;
            for (double r_val : h) {
                if (r_val > 0) gp_h += r_val;
                else           gl_h += std::abs(r_val);
            }
            if (gl_h > 0.0 && (gp_h / gl_h) < 1.0) risk_pct = 0.0025;
        }
        double r_mult = (ev.dir == 1) ? (ev.is_win ? 1.42 : -1.00) : (ev.is_win ? 0.94 : -1.00);
        sym_hist[ev.sym_id].push_back(r_mult);
        if (sym_hist[ev.sym_id].size() > 12) sym_hist[ev.sym_id].pop_front();
        double risk_usd = balance * risk_pct;
        double pnl = risk_usd * r_mult;
        balance += pnl;
        total_trades++;
        int yr = get_year(ev.time_sec);
        auto& ys = yearly[yr];
        ys.trades++;
        ys.net_usd += pnl;
        if (ev.is_win) {
            wins++;
            gross_profit += pnl;
            ys.wins++;
            ys.gross_profit += pnl;
        } else {
            gross_loss += std::abs(pnl);
            ys.gross_loss += std::abs(pnl);
        }
        if (balance > peak) peak = balance;
        double dd = (peak - balance) / peak * 100.0;
        if (dd > max_dd_pct) max_dd_pct = dd;
        csv << total_trades << "," << ev.time_sec << "," << fmt_date(ev.time_sec) << ","
            << (int)ev.sym_id << "," << (ev.dir == 1 ? "BUY" : "SELL") << ","
            << (ev.is_win ? 1 : 0) << "," << std::fixed << std::setprecision(2) << pnl << ","
            << balance << "," << dd << "\n";
    }
    csv.close();
    auto t1 = std::chrono::high_resolution_clock::now();
    double elapsed = std::chrono::duration<double>(t1 - t0).count();
    double pf = (gross_loss > 0.0) ? (gross_profit / gross_loss) : 0.0;
    double wr = (total_trades > 0) ? (100.0 * wins / total_trades) : 0.0;
    std::cout << "\n==========================================================\n";
    std::cout << "  СВОДКА ПО ГОДАМ (ИНДИВИДУАЛЬНЫЕ ПРАВИЛА + ЗАЩИТА PF)\n";
    std::cout << "==========================================================\n";
    std::cout << "  Год   | Сделок | WinRate | Profit Factor | Прирост ($)\n";
    std::cout << "--------+--------+---------+---------------+--------------\n";
    for (const auto& [yr, ys] : yearly) {
        double y_wr = (ys.trades > 0) ? (100.0 * ys.wins / ys.trades) : 0.0;
        double y_pf = (ys.gross_loss > 0.0) ? (ys.gross_profit / ys.gross_loss) : 0.0;
        std::cout << "  " << yr << "  | "
                  << std::setw(6) << ys.trades << " | "
                  << std::fixed << std::setprecision(1) << std::setw(6) << y_wr << "% | "
                  << std::setprecision(2) << std::setw(13) << y_pf << " | "
                  << (ys.net_usd >= 0 ? "+" : "") << "$" << std::setprecision(2) << ys.net_usd << "\n";
    }
    std::cout << "\n==========================================================\n";
    std::cout << "  ИТОГ WALK-FORWARD 9M/3M (" << target_tf << ") — " << std::fixed << std::setprecision(1) << elapsed << " sec\n";
    std::cout << "==========================================================\n";
    std::cout << "OOS Period    : " << fmt_date(first_ts) << " -> " << fmt_date(last_ts) << " (" << window_num << " кварталов)\n";
    std::cout << "Total Trades  : " << total_trades << " (WinRate: " << wr << "%)\n";
    std::cout << "Start Balance : $1,000.00\n";
    std::cout << "Final Balance : $" << std::setprecision(2) << balance << " (+" << std::setprecision(1) << ((balance - 1000.0) / 10.0) << "%)\n";
    std::cout << "Profit Factor : " << std::setprecision(2) << pf << "\n";
    std::cout << "Max Drawdown  : " << std::setprecision(2) << max_dd_pct << "%\n";
    std::cout << "==========================================================\n";
    return 0;
}
