#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <omp.h>
// 36 колонок в data_v3:
// 0:SymbolID, 1:Time,
// 24 непрерывных признака (квантуются в uint8):
// 2:L_c_Norm, 3:L_prev_Norm, 4:Ratio_L, 5:Ema5_8_Diff_Norm, 6:Ema8_21_Diff_Norm,
// 7:MACD_Hist_Norm, 8:MACD_Delta_Norm, 10:Stoch_K, 11:Stoch_D, 13:RSI5, 14:RSI8,
// 15:CCI5, 16:CCI8, 17:VolRatio, 18:OBV_Slope_Norm, 21:FigureScore, 25:PenaltyScore,
// 26:ATR14, 27:ATR_Ratio, 29:HTF_EMA21_Slope_Norm, 30:Price_vs_HTF_EMA21_Norm,
// 32:Impulse_Age, 33:Wick_Reject_Ratio
// 9 дискретных/флаговых колонок (int8/uint8):
// 9:MACD_Inc, 12:Stoch_Cross, 19:FigureID, 20:FigureDir, 22:Heavy_MA_Up,
// 23:Heavy_MACD_Inc, 24:Heavy_Trend_Confirmed, 28:MacroTrendUp, 31:Triple_Trend_Align
// 2 таргета (uint8):
// 34:Target_NextUp, 35:Target_RR
static const int NUM_QFEATS = 23;
static const int QFEAT_COLS[NUM_QFEATS] = {
    2, 3, 4, 5, 6, 7, 8, 10, 11, 13, 14, 15, 16, 17, 18, 21, 25, 26, 27, 29, 30, 32, 33
};
static const int NUM_FLAGS = 9;
static const int FLAG_COLS[NUM_FLAGS] = {
    9, 12, 19, 20, 22, 23, 24, 28, 31
};
#pragma pack(push, 1)
struct V3SliceEntry {
    char timeframe[8];
    uint64_t start_row;
    uint32_t num_rows;
};
struct V3QuantHeader {
    char magic[8];               // "V3QUANT1"
    uint32_t num_slices;
    uint32_t num_qfeats;         // 23
    uint32_t num_flags;          // 9
    uint64_t total_rows;
    uint64_t index_offset;
    float bin_edges[NUM_QFEATS][256];
};
#pragma pack(pop)
inline bool parse_36(const char* line, size_t len, double out[36]) {
    int col = 0;
    const char* p = line;
    const char* end = line + len;
    while (p < end && col < 36) {
        char* next_p = nullptr;
        double v = std::strtod(p, &next_p);
        if (next_p == p) return false;
        out[col++] = v;
        p = next_p;
        if (p < end && *p == ',') ++p;
    }
    return col == 36;
}
struct RawDataset {
    std::string tf;
    std::vector<uint8_t> sym_id;
    std::vector<uint32_t> time_sec;
    std::vector<float> qcols[NUM_QFEATS];
    std::vector<int8_t> flags[NUM_FLAGS];
    std::vector<uint8_t> target_up;
    std::vector<uint8_t> target_rr;
};
RawDataset load_csv(const std::string& path, const std::string& tf) {
    RawDataset ds;
    ds.tf = tf;
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::cerr << "Cannot open " << path << "\n";
        return ds;
    }
    in.seekg(0, std::ios::end);
    size_t fsz = in.tellg();
    in.seekg(0, std::ios::beg);
    size_t est = fsz / 220 + 1024;
    ds.sym_id.reserve(est);
    ds.time_sec.reserve(est);
    for (int f = 0; f < NUM_QFEATS; ++f) ds.qcols[f].reserve(est);
    for (int g = 0; g < NUM_FLAGS; ++g) ds.flags[g].reserve(est);
    ds.target_up.reserve(est);
    ds.target_rr.reserve(est);
    std::string line;
    std::getline(in, line); // skip header
    double vals[36];
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        if (line.back() == '\r') line.pop_back();
        if (!parse_36(line.c_str(), line.size(), vals)) continue;
        ds.sym_id.push_back(static_cast<uint8_t>(vals[0]));
        ds.time_sec.push_back(static_cast<uint32_t>(vals[1]));
        for (int f = 0; f < NUM_QFEATS; ++f)
            ds.qcols[f].push_back(static_cast<float>(vals[QFEAT_COLS[f]]));
        for (int g = 0; g < NUM_FLAGS; ++g)
            ds.flags[g].push_back(static_cast<int8_t>(vals[FLAG_COLS[g]]));
        ds.target_up.push_back(static_cast<uint8_t>(vals[34] > 0.5 ? 1 : 0));
        ds.target_rr.push_back(static_cast<uint8_t>(vals[35] > 0.5 ? 1 : 0));
    }
    std::cout << "Loaded " << tf << ": " << ds.sym_id.size() << " rows\n";
    return ds;
}
void build_cache(const std::string& out_path, const std::vector<RawDataset>& datasets) {
    uint64_t N = 0;
    std::vector<V3SliceEntry> slices;
    for (const auto& ds : datasets) {
        V3SliceEntry se{};
        std::strncpy(se.timeframe, ds.tf.c_str(), 7);
        se.start_row = N;
        se.num_rows = static_cast<uint32_t>(ds.sym_id.size());
        slices.push_back(se);
        N += se.num_rows;
    }
    V3QuantHeader hdr{};
    std::memcpy(hdr.magic, "V3QUANT1", 8);
    hdr.num_slices = static_cast<uint32_t>(slices.size());
    hdr.num_qfeats = NUM_QFEATS;
    hdr.num_flags = NUM_FLAGS;
    hdr.total_rows = N;
    std::vector<std::vector<uint8_t>> q_data(NUM_QFEATS, std::vector<uint8_t>(N));
    for (int f = 0; f < NUM_QFEATS; ++f) {
        std::vector<float> sample;
        sample.reserve(N / 8 + 1024);
        for (const auto& ds : datasets) {
            const auto& col = ds.qcols[f];
            for (size_t i = 0; i < col.size(); i += 8) {
                if (std::isfinite(col[i])) sample.push_back(col[i]);
            }
        }
        std::sort(sample.begin(), sample.end());
        for (int b = 0; b < 256; ++b) {
            size_t pos = static_cast<size_t>((b / 255.0) * (sample.size() - 1));
            hdr.bin_edges[f][b] = sample[pos];
        }
        uint64_t offset = 0;
        for (const auto& ds : datasets) {
            const auto& col = ds.qcols[f];
            size_t sz = col.size();
            #pragma omp parallel for
            for (size_t i = 0; i < sz; ++i) {
                float v = col[i];
                if (!std::isfinite(v)) {
                    q_data[f][offset + i] = 128;
                    continue;
                }
                const float* edges = hdr.bin_edges[f];
                auto it = std::lower_bound(edges, edges + 256, v);
                int bin = static_cast<int>(it - edges);
                if (bin > 255) bin = 255;
                q_data[f][offset + i] = static_cast<uint8_t>(bin);
            }
            offset += sz;
        }
    }
    // Размер тела: sym_id(1) + time_sec(4) + 23*qfeats(1) + 9*flags(1) + target_up(1) + target_rr(1) = 39 байт на строку
    uint64_t body_bytes = N * (1ULL + 4ULL + NUM_QFEATS + NUM_FLAGS + 1ULL + 1ULL);
    hdr.index_offset = sizeof(V3QuantHeader) + body_bytes;
    std::ofstream out(out_path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
    for (const auto& ds : datasets)
        out.write(reinterpret_cast<const char*>(ds.sym_id.data()), ds.sym_id.size());
    for (const auto& ds : datasets)
        out.write(reinterpret_cast<const char*>(ds.time_sec.data()), ds.time_sec.size() * sizeof(uint32_t));
    for (int f = 0; f < NUM_QFEATS; ++f)
        out.write(reinterpret_cast<const char*>(q_data[f].data()), N);
    for (int g = 0; g < NUM_FLAGS; ++g) {
        for (const auto& ds : datasets)
            out.write(reinterpret_cast<const char*>(ds.flags[g].data()), ds.flags[g].size());
    }
    for (const auto& ds : datasets)
        out.write(reinterpret_cast<const char*>(ds.target_up.data()), ds.target_up.size());
    for (const auto& ds : datasets)
        out.write(reinterpret_cast<const char*>(ds.target_rr.data()), ds.target_rr.size());
    out.write(reinterpret_cast<const char*>(slices.data()), slices.size() * sizeof(V3SliceEntry));
    out.close();
    std::cout << "Saved " << out_path << " (" << N << " rows)\n";
}
int main(int argc, char** argv) {
    if (argc < 3) return 1;
    std::string src = argv[1];
    std::string dst = argv[2];
    auto t0 = std::chrono::high_resolution_clock::now();
    std::vector<RawDataset> htf;
    htf.push_back(load_csv(src + "\\dataset_M15.csv", "M15"));
    htf.push_back(load_csv(src + "\\dataset_M30.csv", "M30"));
    htf.push_back(load_csv(src + "\\dataset_H1.csv",  "H1"));
    htf.push_back(load_csv(src + "\\dataset_H4.csv",  "H4"));
    htf.push_back(load_csv(src + "\\dataset_D1.csv",  "D1"));
    build_cache(dst + "\\v3_quant_HTF.bin", htf);
    htf.clear();
    std::vector<RawDataset> m5;
    m5.push_back(load_csv(src + "\\dataset_M5.csv", "M5"));
    build_cache(dst + "\\v3_quant_M5.bin", m5);
    auto t1 = std::chrono::high_resolution_clock::now();
    std::cout << "All done in " << std::chrono::duration<double>(t1 - t0).count() << " sec.\n";
    return 0;
}
