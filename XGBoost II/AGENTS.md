# AGENTS.md — Конституция проекта XGBoost-edge
## 1. Архитектура данных (Binary SoA V3 Cache)
Все исследования и перебор правил выполняются строго на бинарных квантованных кэшах в `data/cache/`:
- `data/cache/v3_quant_HTF.bin` (94.7 MB, 2,546,362 строк): таймфреймы `M15`, `M30`, `H1`, `H4`, `D1` (лежит в репозитории).
- `data/cache/v3_quant_M5.bin` (167.9 MB, 4,512,549 строк): таймфрейм `M5` (скачивается из GitHub Release `v3-cache` при запуске).
### Бинарная структура файла (`#pragma pack(push, 1)`):
1. `V3QuantHeader`:
   - `char magic[8]` (`"V3QUANT1"`)
   - `uint32_t num_slices` (количество таймфреймов в файле)
   - `uint32_t num_qfeats` (`23`)
   - `uint32_t num_flags` (`9`)
   - `uint64_t total_rows` (`N`)
   - `uint64_t index_offset`
   - `float bin_edges[23][256]` (таблица реальных порогов для обратного перевода квантилей `0..255` в код MQL4/5)
2. Тело данных (поколоночно, SoA):
   - `uint8_t sym_id[N]`
   - `uint32_t time_sec[N]` (Unix timestamp)
   - `uint8_t q_data[23][N]` (квантованные признаки `0..255`)
   - `int8_t flags[9][N]` (дискретные флаги)
   - `uint8_t target_up[N]` (`1` если следующая свеча закрылась вверх)
   - `uint8_t target_rr[N]` (`1` если сработал Take Profit по Risk/Reward)
3. Индекс срезов (`V3SliceEntry[num_slices]` по смещению `index_offset`):
   - `char timeframe[8]`, `uint64_t start_row`, `uint32_t num_rows`
### Карта признаков:
- **23 квантованных признака (`q_data[0..22]`):**
  `0:L_c_Norm`, `1:L_prev_Norm`, `2:Ratio_L`, `3:Ema5_8_Diff_Norm`, `4:Ema8_21_Diff_Norm`, `5:MACD_Hist_Norm`, `6:MACD_Delta_Norm`, `7:Stoch_K`, `8:Stoch_D`, `9:RSI5`, `10:RSI8`, `11:CCI5`, `12:CCI8`, `13:VolRatio`, `14:OBV_Slope_Norm`, `15:FigureScore`, `16:PenaltyScore`, `17:ATR14`, `18:ATR_Ratio`, `19:HTF_EMA21_Slope_Norm`, `20:Price_vs_HTF_EMA21_Norm`, `21:Impulse_Age`, `22:Wick_Reject_Ratio`.
- **9 дискретных флагов (`flags[0..8]`):**
  `0:MACD_Inc`, `1:Stoch_Cross`, `2:FigureID`, `3:FigureDir`, `4:Heavy_MA_Up`, `5:Heavy_MACD_Inc`, `6:Heavy_Trend_Confirmed`, `7:MacroTrendUp`, `8:Triple_Trend_Align`.
## 2. Разделение ролей при оркестрации ИИ (Goose / CLI / GitHub Actions)
- **Разведчик (DeepSeek / Gemini):** анализирует выжимки статей MQL5 в `data/passed_edges.jsonl` и формулирует гипотезы признаков.
- **Инженер (Claude):** пишет и оптимизирует C++20-код в `src/` (`-O3 -std=c++20 -fopenmp`) и шаблоны MQL4/5 в `rules/`.
- **Аудитор (ChatGPT / Gemini):** проверяет любой новый C++/MQL код на отсутствие заглядывания в будущее (`look-ahead bias`), утечек таргета (`Target_NextUp`/`Target_RR` запрещено использовать в условиях входа) и подгонки.
## 3. Жёсткие правила отбора стратегий
1. Деление времени, критерии, издержки и порядок экзамена: `registry/SVOD_PRAVIL.md` (утверждено 2026-11-25).
2. Прежние пороги (разделение 70/30, сделок вне выборки не меньше 150, доля побед не меньше 56%) отменены.
3. Все скомпилированные `.exe` и файл `data/cache/v3_quant_M5.bin` запрещено коммитить в Git.
