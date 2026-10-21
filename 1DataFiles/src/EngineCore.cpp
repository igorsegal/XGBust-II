#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <filesystem>
#include <cstdint>

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

// [MCP_INTERNAL_GUARD: Binary File Reader & Header Parser]
bool readBinaryDataset(const fs::path& filePath, std::vector<MqlRatesRecord>& outRecords, int32_t& outPeriod) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "[MCP_LOG] Error: Cannot open file -> " << filePath.string() << std::endl;
        return false;
    }

    char magic[8];
    file.read(magic, 8);
    if (file.gcount() < 8 || std::string(magic, 8) != "XFBAR001") {
        std::cerr << "[MCP_LOG] Error: Invalid magic header -> " << filePath.filename() << std::endl;
        return false;
    }

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

    // [MCP_INTERNAL_GUARD: Strict 60-byte record check]
    if (record_size != 60) {
        std::cerr << "[MCP_LOG] Error: Record size mismatch (" << record_size << ") -> " << filePath.filename() << std::endl;
        return false;
    }

    outRecords.resize(barCount);
    file.read(reinterpret_cast<char*>(outRecords.data()), barCount * sizeof(MqlRatesRecord));
    return true;
}

int main() {
    std::cout << std::unitbuf;
    std::cerr << std::unitbuf;

    // [MCP_INTERNAL_GUARD: Engine Boot Sequence]
    std::cout << "[MCP_BOOT] Initializing QwenGyreEngine Core Pipeline in src..." << std::endl;

    fs::path whitelistPath = "../whitelist_strict.txt";
    if (!fs::exists(whitelistPath)) {
        whitelistPath = "whitelist_strict.txt";
    }
    
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
    if (!fs::exists(rawDir)) {
        std::cerr << "[MCP_FATAL] Raw data directory missing: " << rawDir.string() << std::endl;
        return 1;
    }

    // [MCP_INTERNAL_GUARD: Processing Symbol Datasets]
    for (const auto& sym : symbols) {
        fs::path symDir = rawDir / sym;
        if (!fs::exists(symDir)) continue;

        fs::path m5Path, h1Path;
        for (const auto& entry : fs::directory_iterator(symDir)) {
            if (entry.path().extension() == ".bin") {
                std::ifstream testFile(entry.path(), std::ios::binary);
                if (!testFile.is_open()) continue;
                testFile.seekg(12, std::ios::beg); // Пропуск magic (8) + version (4)
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
                std::cout << "[MCP_ALIGNED] Symbol: " << sym 
                          << " | M5 Bars: " << m5Data.size() 
                          << " | H1 Bars: " << h1Data.size() << std::endl;
                
                // Синхронизация таймфреймов без look-ahead bias
                size_t h1Index = 0;
                int alignedCount = 0;
                for (size_t i = 0; i < m5Data.size(); ++i) {
                    int64_t tM5 = m5Data[i].time;
                    while (h1Index + 1 < h1Data.size() && h1Data[h1Index + 1].time <= tM5) {
                        h1Index++;
                    }
                    if (h1Index < h1Data.size() && tM5 >= h1Data[h1Index].time && tM5 < h1Data[h1Index].time + 3600) {
                        alignedCount++;
                    }
                }
                std::cout << "[MCP_OK] Synchronized intervals for " << sym << ": " << alignedCount << std::endl;
            }
        }
    }

    std::cout << "[MCP_READY] Engine Core execution completed successfully." << std::endl;
    return 0;
}