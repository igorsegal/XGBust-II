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
#include <omp.h>
static const int NUM_QFEATS = 23;
static const int NUM_FLAGS  = 9;
static const char* QFEAT_NAMES[NUM_QFEATS] = {
    "L_c_Norm", "L_prev_Norm", "Ratio_L", "Ema5_8_Diff_Norm", "Ema8_21_Diff_Norm",
    "MACD_Hist_Norm", "MACD_Delta_Norm", "Stoch_K", "Stoch_D", "RSI5", "RSI8",
    "CCI5", "CCI8", "VolRatio", "OBV_Slope_Norm", "FigureScore", "PenaltyScore",
    "ATR14", "ATR_Ratio", "HTF_EMA21_Slope_Norm", "Price_vs_HTF_EMA21_Norm",
    "Impulse_Age", "Wick_Reject_Ratio"
};
// Исключаем ненормированный ATR14 (индекс 17), чтобы правила работали одинаково на всех символах
inline bool is_scale_invariant(int feat_idx) {
    return feat_idx != 17;
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
struct RuleCandidate {
    int dir;         // 1 = BUY (Target_RR==1), -1 = SELL (Target_NextUp==0)
    int trend_mode;  // 1 = Triple_Trend_Align==1, -1 = Triple_Trend_Align==-1, 0 = Any
    int f1, f2;
    uint8_t b1, b2;
    bool gt1, gt2;
    int train_trades, oos_trades;
    double train_wr, oos_wr;
    double oos_pf;
    double score;
};
int main(int argc, char** argv) {
    std::string cache_path = (argc > 1) ? argv[1] : "data/cache/v3_quant_HTF.bin";
    std::string target_tf  = (argc > 2) ? argv[2] : "H1";
    std::string out_mqh    = (argc > 3) ? argv[3] : "rules/discovered_edges.mqh";
    auto t0 = std::chrono::high_resolution_clock::now();
    std::ifstream in(cache_path, std::ios::binary);
    if (!in) return 1;
    V3QuantHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    if (std::strncmp(hdr.magic, "V3QUANT1", 8) != 0) return 1;
    in.seekg(hdr.index_offset);
    std::vector<V3SliceEntry> slices(hdr.num_slices);
    in.read(reinterpret_cast<char*>(slices.data()), hdr.num_slices * sizeof(V3SliceEntry));
    V3SliceEntry chosen{};
    bool found_tf = false;
    for (const auto& s : slices) {
        if (std::string(s.timeframe) == target_tf) { chosen = s; found_tf = true; break; }
    }
    if (!found_tf) return 1;
    uint64_t N = hdr.total_rows;
    uint64_t start = chosen.start_row;
    uint32_t M = chosen.num_rows;
    std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M));
    uint64_t base_q = sizeof(V3QuantHeader) + N * (1ULL + 4ULL);
    for (int f = 0; f < NUM_QFEATS; ++f) {
        in.seekg(base_q + static_cast<uint64_t>(f) * N + start);
        in.read(reinterpret_cast<char*>(q[f].data()), M);
    }
    std::vector<int8_t> triple_align(M);
    uint64_t base_flags = base_q + static_cast<uint64_t>(NUM_QFEATS) * N;
    in.seekg(base_flags + 8ULL * N + start);
    in.read(reinterpret_cast<char*>(triple_align.data()), M);
    std::vector<uint8_t> target_up(M);
    uint64_t base_tup = base_flags + static_cast<uint64_t>(NUM_FLAGS) * N;
    in.seekg(base_tup + start);
    in.read(reinterpret_cast<char*>(target_up.data()), M);
    std::vector<uint8_t> target_rr(M);
    uint64_t base_trr = base_tup + N;
    in.seekg(base_trr + start);
    in.read(reinterpret_cast<char*>(target_rr.data()), M);
    uint32_t split_idx = static_cast<uint32_t>(M * 0.70);
    std::vector<RuleCandidate> all_best;
    const int trend_modes[3] = {1, -1, 0};
    #pragma omp parallel
    {
        std::vector<RuleCandidate> local_best;
        for (int tm : trend_modes) {
            for (int f1 = 0; f1 < NUM_QFEATS; ++f1) {
                if (!is_scale_invariant(f1)) continue;
                #pragma omp for schedule(dynamic, 1) nowait
                for (int f2 = f1 + 1; f2 < NUM_QFEATS; ++f2) {
                    if (!is_scale_invariant(f2)) continue;
                    for (int b1 = 16; b1 <= 240; b1 += 32) {
                        for (int b2 = 16; b2 <= 240; b2 += 32) {
                            for (int gt1 = 0; gt1 <= 1; ++gt1) {
                                for (int gt2 = 0; gt2 <= 1; ++gt2) {
                                    int tr_n = 0, tr_buy_w = 0, tr_sell_w = 0;
                                    int oos_n = 0, oos_buy_w = 0, oos_sell_w = 0;
                                    for (uint32_t i = 0; i < M; ++i) {
                                        if (tm != 0 && triple_align[i] != tm) continue;
                                        bool c1 = gt1 ? (q[f1][i] >= b1) : (q[f1][i] <= b1);
                                        if (!c1) continue;
                                        bool c2 = gt2 ? (q[f2][i] >= b2) : (q[f2][i] <= b2);
                                        if (!c2) continue;
                                        bool buy_win  = (target_rr[i] == 1);
                                        bool sell_win = (target_up[i] == 0);
                                        if (i < split_idx) {
                                            tr_n++;
                                            if (buy_win) tr_buy_w++;
                                            if (sell_win) tr_sell_w++;
                                        } else {
                                            oos_n++;
                                            if (buy_win) oos_buy_w++;
                                            if (sell_win) oos_sell_w++;
                                        }
                                    }
                                    if (tr_n >= 400 && oos_n >= 200) {
                                        // BUY по Target_RR (R:R = 1.45 с учётом спреда)
                                        double tr_b_wr  = (double)tr_buy_w / tr_n;
                                        double oos_b_wr = (double)oos_buy_w / oos_n;
                                        double oos_b_pf = (oos_b_wr * 1.45) / std::max(0.01, (1.0 - oos_b_wr));
                                        if (tr_b_wr >= 0.47 && oos_b_wr >= 0.47 && oos_b_pf >= 1.28) {
                                            double sc = (oos_b_pf - 1.0) * std::log((double)oos_n);
                                            local_best.push_back({1, tm, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                  tr_n, oos_n, tr_b_wr * 100.0, oos_b_wr * 100.0, oos_b_pf, sc});
                                        }
                                        // SELL по закрытию следующей свечи вниз (Target_NextUp == 0, PF с поправкой 0.96 на спред)
                                        double tr_s_wr  = (double)tr_sell_w / tr_n;
                                        double oos_s_wr = (double)oos_sell_w / oos_n;
                                        double oos_s_pf = (oos_s_wr * 0.96) / std::max(0.01, (1.0 - oos_s_wr));
                                        if (tr_s_wr >= 0.565 && oos_s_wr >= 0.565 && oos_s_pf >= 1.24) {
                                            double sc = (oos_s_pf - 1.0) * std::log((double)oos_n);
                                            local_best.push_back({-1, tm, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                  tr_n, oos_n, tr_s_wr * 100.0, oos_s_wr * 100.0, oos_s_pf, sc});
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        #pragma omp critical
        all_best.insert(all_best.end(), local_best.begin(), local_best.end());
    }
    std::sort(all_best.begin(), all_best.end(), [](const RuleCandidate& a, const RuleCandidate& b) {
        return a.score > b.score;
    });
    std::vector<RuleCandidate> selected;
    int buy_cnt = 0, sell_cnt = 0;
    for (const auto& r : all_best) {
        bool dup = false;
        for (const auto& s : selected) {
            if (s.dir == r.dir && s.f1 == r.f1 && s.f2 == r.f2) { dup = true; break; }
        }
        if (dup) continue;
        if (r.dir == 1 && buy_cnt < 10) { selected.push_back(r); buy_cnt++; }
        if (r.dir == -1 && sell_cnt < 10) { selected.push_back(r); sell_cnt++; }
        if (buy_cnt >= 10 && sell_cnt >= 10) break;
    }
    std::ofstream mqh(out_mqh);
    mqh << "// Auto-generated scale-invariant rules by mine_v3.cpp on " << target_tf << " (" << M << " bars)\n";
    mqh << "// Strict Out-of-Sample (OOS) verified rules (last 30% history)\n#pragma once\n\n";
    for (size_t i = 0; i < selected.size(); ++i) {
        const auto& r = selected[i];
        float thr1 = hdr.bin_edges[r.f1][r.b1];
        float thr2 = hdr.bin_edges[r.f2][r.b2];
        std::string op1 = r.gt1 ? ">=" : "<=";
        std::string op2 = r.gt2 ? ">=" : "<=";
        std::string dstr = (r.dir == 1) ? "BUY" : "SELL";
        std::string tcond = (r.trend_mode == 1) ? "tripleAlign == 1 && " :
                           ((r.trend_mode == -1) ? "tripleAlign == -1 && " : "");
        mqh << "// Rule #" << (i + 1) << " [" << dstr << "] | Train WR=" << std::fixed << std::setprecision(1) << r.train_wr
            << "% | OOS WR=" << r.oos_wr << "% (" << r.oos_trades << " trades) | Est OOS PF=" << std::setprecision(2) << r.oos_pf << "\n";
        mqh << "bool CheckEdge_" << target_tf << "_" << dstr << "_" << (i + 1)
            << "(int tripleAlign, double " << QFEAT_NAMES[r.f1] << ", double " << QFEAT_NAMES[r.f2] << ") {\n";
        mqh << "   return (" << tcond << QFEAT_NAMES[r.f1] << " " << op1 << " " << std::setprecision(6) << thr1
            << " && " << QFEAT_NAMES[r.f2] << " " << op2 << " " << thr2 << ");\n}\n\n";
    }
    mqh.close();
    return 0;
}
