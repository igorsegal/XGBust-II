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

struct TradePosition {
    std::string symbol;
    int64_t entryTime;
    double entryPrice;
    double stopLoss;
    double takeProfit;
    double volume;
    bool isLong;
    bool isActive;
};

// [MCP_INTERNAL_GUARD: Binary Reader Audit]
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

    if (record_size != 60) return false;

    outRecords.resize(barCount);
    file.read(reinterpret_cast<char*>(outRecords.data()), barCount * sizeof(MqlRatesRecord));
    return true;
}

class RiskManagerEngine {
private:
    double initialBalance = 10000.0;
    double currentBalance = 10000.0;
    double maxDrawdownPct = 0.0;
    double peakBalance = 10000.0;
    double riskPerTrade = 0.01; // 1% риска на сделку

public:
    // [MCP_INTERNAL_GUARD: Trade Simulation & Risk Control]
    void simulateTradesAndManageRisk(const std::string& symbol, const std::vector<MqlRatesRecord>& m5Data, const std::vector<MqlRatesRecord>& h1Data) {
        if (m5Data.empty() || h1Data.empty()) return;

        std::cout << "[MCP_RISK] Initiating trade execution & risk simulation for -> " << symbol << std::endl;

        size_t h1Index = 0;
        int totalTrades = 0;
        int winTrades = 0;
        TradePosition activeTrade = {};
        activeTrade.isActive = false;

        for (size_t i = 20; i < m5Data.size(); ++i) {
            int64_t tM5 = m5Data[i].time;

            while (h1Index + 1 < h1Data.size() && h1Data[h1Index + 1].time <= tM5) {
                h1Index++;
            }

            // [MCP_INTERNAL_GUARD: Active Position Risk Management]
            if (activeTrade.isActive) {
                // Проверка условий выходя по SL / TP
                if (m5Data[i].low <= activeTrade.stopLoss) {
                    // Закрытие по Стоп-Лоссу
                    double loss = (activeTrade.entryPrice - activeTrade.stopLoss) * activeTrade.volume;
                    currentBalance -= loss;
                    activeTrade.isActive = false;
                    totalTrades++;
                } else if (m5Data[i].high >= activeTrade.takeProfit) {
                    // Закрытие по Тейк-Профиту
                    double profit = (activeTrade.takeProfit - activeTrade.entryPrice) * activeTrade.volume;
                    currentBalance += profit;
                    activeTrade.isActive = false;
                    totalTrades++;
                    winTrades++;
                }
            }

            // Обновление пикового баланса и учет просадки
            if (currentBalance > peakBalance) {
                peakBalance = currentBalance;
            } else {
                double dd = (peakBalance - currentBalance) / peakBalance * 100.0;
                if (dd > maxDrawdownPct) maxDrawdownPct = dd;
            }

            // Вход в сделку при отсутствии активных позиций
            if (!activeTrade.isActive && h1Index < h1Data.size() && tM5 >= h1Data[h1Index].time) {
                bool h1Bullish = h1Data[h1Index].close >= h1Data[h1Index].open;
                
                double avgVol = 0;
                for (size_t j = i - 20; j < i; ++j) avgVol += m5Data[j].tick_volume;
                avgVol /= 20.0;

                // Генерация сигнала входа
                if (m5Data[i].tick_volume > (avgVol * 3.0) && h1Bullish && (m5Data[i].close > m5Data[i].open)) {
                    double entryPrice = m5Data[i].close;
                    double slDistance = entryPrice * 0.005; // 0.5% SL
                    double stopLoss = entryPrice - slDistance;
                    double takeProfit = entryPrice + (slDistance * 2.0); // R:R 1:2

                    double riskAmount = currentBalance * riskPerTrade;
                    double volume = riskAmount / slDistance;

                    activeTrade = { symbol, tM5, entryPrice, stopLoss, takeProfit, volume, true, true };
                }
            }
        }

        std::cout << "[MCP_RISK_SUMMARY] " << symbol 
                  << " | Trades: " << totalTrades 
                  << " | Wins: " << winTrades 
                  << " | Final Balance: $" << currentBalance 
                  << " | Max Drawdown: " << maxDrawdownPct << "%" << std::endl;
    }
};

int main() {
    std::cout << std::unitbuf;
    std::cerr << std::unitbuf;

    std::cout << "[MCP_BOOT] Initializing RiskManager module..." << std::endl;

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
    RiskManagerEngine riskManager;

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
                riskManager.simulateTradesAndManageRisk(sym, m5Data, h1Data);
            }
        }
    }

    std::cout << "[MCP_READY] RiskManager simulation completed successfully." << std::endl;
    return 0;
}