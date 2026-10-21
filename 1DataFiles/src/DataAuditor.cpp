#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <filesystem>
#include <cstdint>
#include <algorithm>
#include <cctype>

namespace fs = std::filesystem;

#pragma pack(push, 1)
struct MqlRatesRecord {
    int64_t time;          // 8 байт: Unix timestamp
    double open;           // 8 байт
    double high;           // 8 байт
    double low;            // 8 байт
    double close;          // 8 байт
    int64_t tick_volume;   // 8 байт
    int32_t spread;        // 4 байт
    int64_t real_volume;   // 8 байт
};
#pragma pack(pop)

// Функция проверки: является ли символ акцией или экзотикой, которую нужно исключить
bool shouldSkipSymbol(const std::string& symbol) {
    // 1. Исключаем экзотические валютные пары
    std::vector<std::string> exotics = {
        "HUF", "CZK", "PLN", "MXN", "ZAR", "TRY", "BRL", "SGD", "HKD", 
        "DKK", "NOK", "SEK", "THB", "IDR", "PHP", "INR", "CLP", "COP", 
        "PEN", "TWD", "RUB", "ILS", "RON", "BGN"
    };
    for (const auto& ex : exotics) {
        if (symbol.find(ex) != std::string::npos) return true;
    }

    // 2. Исключаем чистые акции (обычно короткие буквенные тикеры без суффиксов FX/Crypto/Index)
    // Если тикер состоит исключительно из букв (нет цифр, нет дефисов, длина от 1 до 5) и это не известный мажор/крипта
    bool isAllAlpha = true;
    for (char c : symbol) {
        if (!std::isalpha(static_cast<unsigned char>(c))) {
            isAllAlpha = false;
            break;
        }
    }

    if (isAllAlpha && symbol.length() <= 5) {
        // Проверим, не является ли это известным сырьем или индексом
        std::vector<std::string> allowedAlpha = {
            "GOLD", "SILVER", "OIL", "WTI", "BRENT"
        };
        bool allowed = false;
        for (const auto& al : allowedAlpha) {
            if (symbol == al) { allowed = true; break; }
        }
        if (!allowed) {
            return true; // Это акция — исключаем
        }
    }

    return false;
}

bool auditBinaryFile(const fs::path& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) return false;

    char magic[8];
    file.read(magic, 8);
    if (file.gcount() < 8 || std::string(magic, 8) != "XFBAR001") return false;

    int32_t version = 0;
    int32_t record_size = 0;
    int32_t period_seconds = 0;
    int32_t digits = 0;
    double point = 0.0;
    int64_t bar_count = 0;
    int64_t first_time = 0;
    int64_t last_time = 0;
    int32_t symbol_len = 0;

    file.read(reinterpret_cast<char*>(&version), sizeof(version));
    file.read(reinterpret_cast<char*>(&record_size), sizeof(record_size));
    file.read(reinterpret_cast<char*>(&period_seconds), sizeof(period_seconds));
    file.read(reinterpret_cast<char*>(&digits), sizeof(digits));
    file.read(reinterpret_cast<char*>(&point), sizeof(point));
    file.read(reinterpret_cast<char*>(&bar_count), sizeof(bar_count));
    file.read(reinterpret_cast<char*>(&first_time), sizeof(first_time));
    file.read(reinterpret_cast<char*>(&last_time), sizeof(last_time));
    file.read(reinterpret_cast<char*>(&symbol_len), sizeof(symbol_len));

    if (record_size != 60 || bar_count < 100) return false; // Отсекаем слишком короткие файлы

    file.seekg(symbol_len, std::ios::cur);

    MqlRatesRecord prevBar{};
    bool isFirst = true;
    int64_t anomalyCount = 0;
    int64_t gapCount = 0;

    // Максимально допустимый разрыв (например, х4 от периода таймфрейма для будних дней)
    int64_t maxAllowedGap = period_seconds * 4;

    for (int64_t i = 0; i < bar_count; ++i) {
        MqlRatesRecord bar;
        file.read(reinterpret_cast<char*>(&bar), sizeof(MqlRatesRecord));
        if (!file) return false;

        // Проверка цен на аномалии
        if (bar.open <= 0.0 || bar.high <= 0.0 || bar.low <= 0.0 || bar.close <= 0.0) {
            anomalyCount++;
        }

        // Проверка разрывов времени
        if (!isFirst) {
            int64_t timeDiff = bar.time - prevBar.time;
            if (timeDiff > maxAllowedGap) {
                // Игнорируем стандартный выходной (пятница вечер -> понедельник утро: от 48 до 72 часов)
                bool isWeekendGap = (timeDiff >= 172800 && timeDiff <= 259200);
                if (!isWeekendGap) {
                    gapCount++;
                }
            }
        }

        prevBar = bar;
        isFirst = false;
    }

    // Жесткие критерии: ноль аномалий и количество разрывов не более 0.1% от общего числа баров
    if (anomalyCount > 0 || gapCount > (bar_count * 0.001)) {
        return false;
    }

    return true;
}

int main() {
    std::cout << std::unitbuf;
    std::cerr << std::unitbuf;

    std::cout << "[MCP ШАГ 1] Запуск жесткого аудита с фильтрацией акций и экзотики..." << std::endl;

    std::string rootDir = R"(D:\AHexaTrader\1DataFiles\raw)";
    if (!fs::exists(rootDir)) {
        std::cerr << "[MCP ОШИБКА] Директория не найдена." << std::endl;
        return 1;
    }

    std::ofstream whitelist("whitelist_strict.txt");
    int totalInstruments = 0;
    int validInstruments = 0;
    int skippedByFilter = 0;

    for (const auto& entry : fs::directory_iterator(rootDir)) {
        if (entry.is_directory()) {
            std::string symbol = entry.path().filename().string();
            totalInstruments++;

            // Исключаем акции и экзотику досрочно
            if (shouldSkipSymbol(symbol)) {
                skippedByFilter++;
                continue;
            }

            bool allTfValid = true;
            int tfCount = 0;

            for (const auto& fileEntry : fs::directory_iterator(entry.path())) {
                if (fileEntry.path().extension() == ".bin") {
                    tfCount++;
                    if (!auditBinaryFile(fileEntry.path())) {
                        allTfValid = false;
                        break;
                    }
                }
            }

            if (tfCount > 0 && allTfValid) {
                whitelist << symbol << std::endl;
                validInstruments++;
                std::cout << "[НИРВАНА] Инструмент прошел строгий аудит: " << symbol << std::endl;
            }
        }
    }

    whitelist.close();
    std::cout << "\n[MCP ШАГ 2] Строгий аудит завершен." << std::endl;
    std::cout << "Всего папок: " << totalInstruments << std::endl;
    std::cout << "Отсечено фильтром (акции/экзотика): " << skippedByFilter << std::endl;
    std::cout << "Отобрано в strict_whitelist: " << validInstruments << std::endl;

    return 0;
}