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

struct TimeframeData {
    std::string symbol;
    std::string timeframe;
    fs::path filePath;
    int64_t periodSeconds;
    int64_t barCount;
};

// [MCP_INTERNAL_GUARD: Header Verification Routine]
// Validates XFBAR binary signature and record size alignment (strict 60 bytes).
bool verifyFileHeaderMCP(const fs::path& path, int64_t& outBarCount, int32_t& outPeriod) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "[MCP_LOG] Error: Unable to open file -> " << path.string() << std::endl;
        return false;
    }

    char magic[8];
    file.read(magic, 8);
    if (file.gcount() < 8 || std::string(magic, 8) != "XFBAR001") {
        std::cerr << "[MCP_LOG] Error: Invalid magic number -> " << path.filename() << std::endl;
        return false;
    }

    int32_t version, record_size, digits, symbol_len;
    double point;
    int64_t first_time, last_time;

    file.read(reinterpret_cast<char*>(&version), sizeof(version));
    file.read(reinterpret_cast<char*>(&record_size), sizeof(record_size));
    file.read(reinterpret_cast<char*>(&outPeriod), sizeof(outPeriod));
    file.read(reinterpret_cast<char*>(&digits), sizeof(digits));
    file.read(reinterpret_cast<char*>(&point), sizeof(point));
    file.read(reinterpret_cast<char*>(&outBarCount), sizeof(outBarCount));
    file.read(reinterpret_cast<char*>(&first_time), sizeof(first_time));
    file.read(reinterpret_cast<char*>(&last_time), sizeof(last_time));
    file.read(reinterpret_cast<char*>(&symbol_len), sizeof(symbol_len));

    // [MCP_INTERNAL_GUARD: Strict 60-byte record enforcement]
    if (record_size != 60) {
        std::cerr << "[MCP_LOG] Error: Record size mismatch (expected 60, got " << record_size << ") -> " << path.filename() << std::endl;
        return false;
    }

    return true;
}

int main() {
    std::cout << std::unitbuf;
    std::cerr << std::unitbuf;

    // [MCP_INTERNAL_GUARD: Environment Boot Check]
    std::cout << "[MCP_BOOT] Initializing data loader framework from src..." << std::endl;

    // [MCP_INTERNAL_GUARD: Whitelist Presence Check (parent directory lookup)]
    fs::path whitelistPath = "../whitelist_strict.txt";
    if (!fs::exists(whitelistPath)) {
        // Fallback to absolute or local check if needed
        whitelistPath = "whitelist_strict.txt";
    }
    
    if (!fs::exists(whitelistPath)) {
        std::cerr << "[MCP_FATAL] Missing required config: whitelist_strict.txt" << std::endl;
        return 1;
    }

    std::ifstream whitelist(whitelistPath);
    std::vector<std::string> symbols;
    std::string line;
    while (std::getline(whitelist, line)) {
        if (!line.empty()) {
            symbols.push_back(line);
        }
    }
    whitelist.close();

    // [MCP_INTERNAL_GUARD: Data Directory Access Verification]
    fs::path rawDir = R"(D:\AHexaTrader\1DataFiles\raw)";
    if (!fs::exists(rawDir) || !fs::is_directory(rawDir)) {
        std::cerr << "[MCP_FATAL] Invalid raw data root directory: " << rawDir.string() << std::endl;
        return 1;
    }

    std::vector<TimeframeData> activeDatasets;

    // [MCP_INTERNAL_GUARD: Dataset Iteration & M5/H1 Filtering]
    for (const auto& sym : symbols) {
        fs::path symDir = rawDir / sym;
        if (!fs::exists(symDir)) continue;

        for (const auto& entry : fs::directory_iterator(symDir)) {
            if (entry.path().extension() == ".bin") {
                int64_t barCount = 0;
                int32_t period = 0;
                
                if (verifyFileHeaderMCP(entry.path(), barCount, period)) {
                    // Target periods: 300 (M5) and 3600 (H1)
                    if (period == 300 || period == 3600) {
                        activeDatasets.push_back({
                            sym, 
                            (period == 300 ? "M5" : "H1"), 
                            entry.path(), 
                            period, 
                            barCount
                        });
                    }
                }
            }
        }
    }

    std::cout << "[MCP_READY] Loaded datasets count: " << activeDatasets.size() << std::endl;
    return 0;
}