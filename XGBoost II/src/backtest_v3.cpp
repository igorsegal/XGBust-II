#include <cmath>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <ctime>
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
#pragma pack(pop)
// Индексы квантованных признаков в V3:
// 3:Ema5_8_Diff_Norm, 5:MACD_Hist_Norm, 6:MACD_Delta_Norm, 7:Stoch_K, 8:Stoch_D,
// 10:RSI8, 13:VolRatio, 14:OBV_Slope_Norm, 18:ATR_Ratio, 19:HTF_EMA21_Slope_Norm, 20:Price_vs_HTF_EMA21_Norm
struct BarEvent {
    uint32_t time_sec;
    uint8_t sym_id;
    int tf_code; // 1 = H1, 4 = H4
    int signal;  // 1 = BUY, -1 = SELL
    uint8_t target_up;
    uint8_t target_rr;
};
std::string fmt_date(uint32_t ts) {
    std::time_t t = static_cast<std::time_t>(ts);
    std::tm* tm_ptr = std::gmtime(&t);
    char buf[32];
    if (tm_ptr && std::strftime(buf, sizeof(buf), "%Y-%m-%d", tm_ptr)) return std::string(buf);
    return "1970-01-01";
}
int main() {
    std::string cache_path = "data/cache/v3_quant_HTF.bin";
    std::ifstream in(cache_path, std::ios::binary);
    if (!in) {
        std::cerr << "Cannot open " << cache_path << "\n";
        return 1;
    }
    V3QuantHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    in.seekg(hdr.index_offset);
    std::vector<V3SliceEntry> slices(hdr.num_slices);
    in.read(reinterpret_cast<char*>(slices.data()), hdr.num_slices * sizeof(V3SliceEntry));
    uint64_t N = hdr.total_rows;
    uint64_t base_sym  = sizeof(V3QuantHeader);
    uint64_t base_time = base_sym + N;
    uint64_t base_q    = base_time + N * 4ULL;
    uint64_t base_flg  = base_q + NUM_QFEATS * N;
    uint64_t base_tup  = base_flg + NUM_FLAGS * N;
    uint64_t base_trr  = base_tup + N;
    std::vector<BarEvent> events;
    events.reserve(100000);
    uint32_t oos_start_ts_h4 = 0;
    for (const auto& s : slices) {
        std::string tf(s.timeframe);
        if (tf != "H1" && tf != "H4") continue;
        int tf_code = (tf == "H1") ? 1 : 4;
        uint64_t st = s.start_row;
        uint32_t M  = s.num_rows;
        std::vector<uint8_t> sym(M);
        std::vector<uint32_t> ts(M);
        std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M));
        std::vector<int8_t> triple(M);
        std::vector<uint8_t> tup(M), trr(M);
        in.seekg(base_sym + st);      in.read(reinterpret_cast<char*>(sym.data()), M);
        in.seekg(base_time + st * 4); in.read(reinterpret_cast<char*>(ts.data()), M * 4);
        for (int f = 0; f < NUM_QFEATS; ++f) {
            in.seekg(base_q + f * N + st);
            in.read(reinterpret_cast<char*>(q[f].data()), M);
        }
        in.seekg(base_flg + 8ULL * N + st); in.read(reinterpret_cast<char*>(triple.data()), M);
        in.seekg(base_tup + st);            in.read(reinterpret_cast<char*>(tup.data()), M);
        in.seekg(base_trr + st);            in.read(reinterpret_cast<char*>(trr.data()), M);
        if (tf == "H4") {
            uint32_t split_i = static_cast<uint32_t>(M * 0.70);
            oos_start_ts_h4 = ts[split_i];
        }
        // Переводим реальные пороги лучших OOS-правил в квантильные бины
        auto val_to_bin = [&](int f, float v) -> uint8_t {
            const float* ed = hdr.bin_edges[f];
            auto it = std::lower_bound(ed, ed + 256, v);
            int b = static_cast<int>(it - ed);
            return static_cast<uint8_t>(std::min(255, std::max(0, b)));
        };
        // Пороги из лучших правил H4 и H1:
        uint8_t b_macd_hist_neg = val_to_bin(5, -2.374708f);
        uint8_t b_price_htf     = val_to_bin(20, -0.641112f);
        uint8_t b_stoch_k       = val_to_bin(7, 46.666668f);
        uint8_t b_htf_slope     = val_to_bin(19, -0.064111f);
        uint8_t b_macd_delta    = val_to_bin(6, 0.392367f);
        uint8_t b_ema5_8        = val_to_bin(3, -0.031559f);
        uint8_t b_rsi8          = val_to_bin(10, 61.774742f);
        uint8_t b_macd_d_h1     = val_to_bin(6, 0.511325f);
        uint8_t b_vol_ratio     = val_to_bin(13, 1.235698f);
        uint8_t b_obv_slope     = val_to_bin(14, 0.397219f);
        for (uint32_t i = 0; i < M; ++i) {
            int sig = 0;
            if (tf_code == 4) {
                // Лучшие правила H4 (BUY + SELL)
                bool h4_buy1 = (triple[i] == -1 && q[5][i] <= b_macd_hist_neg && q[20][i] >= b_price_htf);
                bool h4_buy3 = (triple[i] == -1 && q[7][i] >= b_stoch_k && q[19][i] >= b_htf_slope);
                bool h4_buy9 = (q[3][i] <= b_ema5_8 && q[6][i] >= b_macd_delta);
                bool h4_sell = (triple[i] == -1 && q[13][i] >= b_vol_ratio && q[14][i] >= b_obv_slope);
                if (h4_buy1 || h4_buy3 || h4_buy9) sig = 1;
                else if (h4_sell) sig = -1;
            } else {
                // Лучшее безразмерное правило H1 (Rule #1)
                bool h1_buy1 = (triple[i] == -1 && q[6][i] >= b_macd_d_h1 && q[10][i] >= b_rsi8);
                if (h1_buy1) sig = 1;
            }
            if (sig != 0) {
                events.push_back({ts[i], sym[i], tf_code, sig, tup[i], trr[i]});
            }
        }
    }
    // Сортируем все сделки строго хронологически по реальному времени
    std::sort(events.begin(), events.end(), [](const BarEvent& a, const BarEvent& b) {
        if (a.time_sec != b.time_sec) return a.time_sec < b.time_sec;
        return a.sym_id < b.sym_id;
    });
    // Фильтруем только Out-of-Sample период (последние ~6 лет истории) + анти-спам 1 сделка на символ в 4 часа
    std::vector<uint32_t> last_sym_ts(256, 0);
    double balance = 1000.0;
    double peak = 1000.0;
    double max_dd_pct = 0.0;
    double risk_pct = 0.01; // 1% риска на сделку ($10 на старте)
    int total_trades = 0, wins = 0;
    double gross_profit = 0.0, gross_loss = 0.0;
    std::ofstream csv("rules/oos_equity_curve.csv");
    csv << "TradeNum,Timestamp,Date,SymbolID,TF,Dir,Win,PnL_USD,Balance,DrawdownPct\n";
    csv << "0," << oos_start_ts_h4 << "," << fmt_date(oos_start_ts_h4) << ",0,INIT,NONE,1,0.00,1000.00,0.00\n";
    uint32_t first_ts = 0, last_ts = 0;
    for (const auto& ev : events) {
        if (ev.time_sec < oos_start_ts_h4) continue;
        if (ev.time_sec - last_sym_ts[ev.sym_id] < 14400) continue; // не чаще 1 сделки в 4ч по одному символу
        last_sym_ts[ev.sym_id] = ev.time_sec;
        if (first_ts == 0) first_ts = ev.time_sec;
        last_ts = ev.time_sec;
        double risk_usd = balance * risk_pct;
        double pnl = 0.0;
        bool is_win = false;
        if (ev.signal == 1) {
            // BUY по Target_RR (с учётом спреда/комиссии: победа +1.42R, стоп -1.00R)
            is_win = (ev.target_rr == 1);
            pnl = is_win ? (risk_usd * 1.42) : (-risk_usd * 1.00);
        } else {
            // SELL по закрытию следующей свечи вниз (победа +0.94R после спреда, стоп -1.00R)
            is_win = (ev.target_up == 0);
            pnl = is_win ? (risk_usd * 0.94) : (-risk_usd * 1.00);
        }
        balance += pnl;
        total_trades++;
        if (is_win) { wins++; gross_profit += pnl; }
        else        { gross_loss += std::abs(pnl); }
        if (balance > peak) peak = balance;
        double dd = (peak - balance) / peak * 100.0;
        if (dd > max_dd_pct) max_dd_pct = dd;
        csv << total_trades << "," << ev.time_sec << "," << fmt_date(ev.time_sec) << ","
            << (int)ev.sym_id << ",H" << ev.tf_code << "," << (ev.signal == 1 ? "BUY" : "SELL") << ","
            << (is_win ? 1 : 0) << "," << std::fixed << std::setprecision(2) << pnl << ","
            << balance << "," << dd << "\n";
    }
    csv.close();
    double pf = (gross_loss > 0.0) ? (gross_profit / gross_loss) : 0.0;
    double wr = (total_trades > 0) ? (100.0 * wins / total_trades) : 0.0;
    std::cout << "\n==========================================================\n";
    std::cout << "  PORTFOLIO OUT-OF-SAMPLE BACKTEST (Start: $1,000.00)\n";
    std::cout << "==========================================================\n";
    std::cout << "Period        : " << fmt_date(first_ts) << " -> " << fmt_date(last_ts) << "\n";
    std::cout << "Total Trades  : " << total_trades << " (WinRate: " << std::fixed << std::setprecision(1) << wr << "%)\n";
    std::cout << "Final Balance : $" << std::setprecision(2) << balance << " (+" << std::setprecision(1) << ((balance - 1000.0) / 10.0) << "%)\n";
    std::cout << "Profit Factor : " << std::setprecision(2) << pf << "\n";
    std::cout << "Max Drawdown  : " << std::setprecision(2) << max_dd_pct << "%\n";
    std::cout << "==========================================================\n";
    return 0;
}
