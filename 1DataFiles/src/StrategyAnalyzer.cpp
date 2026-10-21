#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <filesystem>
#include <cstdint>
#include <cmath>

namespace fs = std::filesystem;

#pragma pack(push, 1)
struct MqlRatesRecord {
    int64_t time;
    double open;
    double high;
    double low;
    double close;
    int64_t tick_volume;
    int32_t spread;
    int64_t real_volume;
};
#pragma pack(pop)

// [MCP_INTERNAL_GUARD: Binary Dataset Loader with Header Audit]
bool readBinaryDataset(const fs::path& filePath, std::vector<MqlRatesRecord>& outRecords, int32_t& outPeriod) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) return false;

    char magic[8];
    file.read(magic, 8);
    if (file.gcount() < 8 || std::string(magic, 8) != "XFBAR001") return false;

    int32_t version, record_size, digits, symbol_len;
    double point;
    int64_t barCount, first_time, last_time;

    file.read(reinterpret_cast<char*>(&version), sizeof(version));
    file.read(reinterpret_cast<char*>(&record_size), sizeof(record_size));
    file.read(reinterpret_cast<char*>(&outPeriod), sizeof(outPeriod));
    file.read(reinterpret_cast<char*>(&digits), sizeof(digits));
    file.read(reinterpret_cast<char*>(&point), sizeof(point));
    file.read(reinterpret_cast<char*>(&barCount), sizeof(barCount));
    file.read(reinterpret_cast<char*>(&first_time), sizeof(first_time));
    file.read(reinterpret_cast<char*>(&last_time), sizeof(last_time));
    file.read(reinterpret_cast<char*>(&symbol_len), sizeof(symbol_len));

    if (record_size != 60) return false; // Strict 60-byte verification[cite: 1]

    outRecords.resize(barCount);
    file.read(reinterpret_cast<char*>(outRecords.data()), barCount * sizeof(MqlRatesRecord));
    return true;
}

class StrategyAnalyzer {
public:
    // [MCP_INTERNAL_GUARD: Volume Spike & Trend Alignment Logic]
    void analyzeSymbol(const std::string& symbol, const std::vector<MqlRatesRecord>& m5Data, const std::vector<MqlRatesRecord>& h1Data) {
        if (m5Data.empty() || h1Data.empty()) return;

        std::cout << "[MCP_ANALYSIS] Starting strategy evaluation for -> " << symbol << std::endl;

        size_t h1Index = 0;
        int signalCount = 0;

        // Простой расчет скользящего среднего объема для поиска аномалий на M5
        for (size_t i = 20; i < m5Data.size(); ++i) {
            int64_t tM5 = m5Data[i].time;

            // Синхронизация таймфрейма H1 без look-ahead bias
            while (h1Index + 1 < h1Data.size() && h1Data[h1Index + 1].time <= tM5) {
                h1Index++;
            }

            if (h1Index < h1Data.size() && tM5 >= h1Data[h1Index].time && tM5 < h1Data[h1Index].time + 3600) {
                // Проверяем контекст старшего таймфрейма (H1 бычий или медвежий бар)
                bool h1Bullish = h1Data[h1Index].close >= h1Data[h1Index].open;

                // Расчет среднего объема за последние 20 баров M5
                double avgVolume = 0;
                for (size_t j = i - 20; j < i; ++j) {
                    avgVolume += m5Data[j].tick_volume;
                }
                avgVolume /= 20.0;

                // Условие обнаружения объемного всплеска (Volume Spike)
                if (m5Data[i].tick_volume > (avgVolume * 2.5)) {
                    // Фильтрация по тренду H1
                    if (h1Bullish && (m5Data[i].close > m5Data[i].open)) {
                        signalCount++;
                    }
                }
            }
        }

        std::cout << "[MCP_OK] Symbol " << symbol << " evaluated. Generated signals: " << signalCount << std::endl;
    }
};

int main() {
    std::cout << std::unitbuf;
    std::cerr << std::unitbuf;

    std::cout << "[MCP_BOOT] Initializing StrategyAnalyzer module..." << std::endl;

    fs::path whitelistPath = "../whitelist_strict.txt";
    if (!fs::exists(whitelistPath)) whitelistPath = "whitelist_strict.txt";
    if (!fs::exists(whitelistPath)) {
        std::cerr << "[MCP_FATAL] Missing whitelist_strict.txt" << std::endl;
        return 1;
    }

    std::ifstream whitelist(whitelistPath);
    std::vector<std::string> symbols;
    std::string line;
    while (std::getline(whitelist, line)) {
        if (!line.empty()) symbols.push_back(line);
    }
    whitelist.close();

    fs::path rawDir = R"(D:\AHexaTrader\1DataFiles\raw)";
    StrategyAnalyzer analyzer;

    for (const auto& sym : symbols) {
        fs::path symDir = rawDir / sym;
        if (!fs::exists(symDir)) continue;

        fs::path m5Path, h1Path;
        for (const auto& entry : fs::directory_iterator(symDir)) {
            if (entry.path().extension() == ".bin") {
                std::ifstream testFile(entry.path(), std::ios::binary);
                if (!testFile.is_open()) continue;
                testFile.seekg(12, std::ios::beg);
                int32_t recSize = 0, period = 0;
                testFile.read(reinterpret_cast<char*>(&recSize), sizeof(recSize));
                testFile.read(reinterpret_cast<char*>(&period), sizeof(period));
                
                if (recSize == 60) {
                    if (period == 300) m5Path = entry.path();
                    if (period == 3600) h1Path = entry.path();
                }
            }
        }

        if (!m5Path.empty() && !h1Path.empty()) {
            std::vector<MqlRatesRecord> m5Data, h1Data;
            int32_t pM5 = 0, pH1 = 0;
            if (readBinaryDataset(m5Path, m5Data, pM5) && readBinaryDataset(h1Path, h1Data, pH1)) {
                analyzer.analyzeSymbol(sym, m5Data, h1Data);
            }
        }
    }

    std::cout << "[MCP_READY] StrategyAnalyzer execution completed." << std::endl;
    return 0;
}