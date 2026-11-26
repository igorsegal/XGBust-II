// Auto-generated scale-invariant rules by mine_v3.cpp on H4 (85755 bars)
// Strict Out-of-Sample (OOS) verified rules (last 30% history)
#pragma once

// Rule #1 [BUY] | Train WR=47.0% | OOS WR=52.2% (1865 trades) | Est OOS PF=1.58
bool CheckEdge_H4_BUY_1(int tripleAlign, double MACD_Hist_Norm, double Price_vs_HTF_EMA21_Norm) {
   return (tripleAlign == -1 && MACD_Hist_Norm <= -2.374708 && Price_vs_HTF_EMA21_Norm >= -0.641112);
}

// Rule #2 [BUY] | Train WR=47.0% | OOS WR=52.2% (1865 trades) | Est OOS PF=1.58
bool CheckEdge_H4_BUY_2(int tripleAlign, double MACD_Hist_Norm, double HTF_EMA21_Slope_Norm) {
   return (tripleAlign == -1 && MACD_Hist_Norm <= -2.374708 && HTF_EMA21_Slope_Norm >= -0.064111);
}

// Rule #3 [BUY] | Train WR=47.8% | OOS WR=54.1% (455 trades) | Est OOS PF=1.71
bool CheckEdge_H4_BUY_3(int tripleAlign, double Stoch_K, double HTF_EMA21_Slope_Norm) {
   return (tripleAlign == -1 && Stoch_K >= 46.666668 && HTF_EMA21_Slope_Norm >= -0.064111);
}

// Rule #4 [BUY] | Train WR=47.8% | OOS WR=54.1% (455 trades) | Est OOS PF=1.71
bool CheckEdge_H4_BUY_4(int tripleAlign, double Stoch_K, double Price_vs_HTF_EMA21_Norm) {
   return (tripleAlign == -1 && Stoch_K >= 46.666668 && Price_vs_HTF_EMA21_Norm >= -0.641112);
}

// Rule #5 [BUY] | Train WR=47.9% | OOS WR=52.7% (546 trades) | Est OOS PF=1.62
bool CheckEdge_H4_BUY_5(int tripleAlign, double Stoch_D, double HTF_EMA21_Slope_Norm) {
   return (tripleAlign == -1 && Stoch_D >= 46.872471 && HTF_EMA21_Slope_Norm >= -0.064111);
}

// Rule #6 [BUY] | Train WR=47.9% | OOS WR=52.7% (546 trades) | Est OOS PF=1.62
bool CheckEdge_H4_BUY_6(int tripleAlign, double Stoch_D, double Price_vs_HTF_EMA21_Norm) {
   return (tripleAlign == -1 && Stoch_D >= 46.872471 && Price_vs_HTF_EMA21_Norm >= -0.641112);
}

// Rule #7 [BUY] | Train WR=47.2% | OOS WR=51.2% (1737 trades) | Est OOS PF=1.52
bool CheckEdge_H4_BUY_7(int tripleAlign, double MACD_Delta_Norm, double HTF_EMA21_Slope_Norm) {
   return (tripleAlign == -1 && MACD_Delta_Norm >= 0.236043 && HTF_EMA21_Slope_Norm >= -0.064111);
}

// Rule #8 [BUY] | Train WR=47.2% | OOS WR=51.2% (1737 trades) | Est OOS PF=1.52
bool CheckEdge_H4_BUY_8(int tripleAlign, double MACD_Delta_Norm, double Price_vs_HTF_EMA21_Norm) {
   return (tripleAlign == -1 && MACD_Delta_Norm >= 0.236043 && Price_vs_HTF_EMA21_Norm >= -0.641112);
}

// Rule #9 [BUY] | Train WR=50.2% | OOS WR=51.0% (1463 trades) | Est OOS PF=1.51
bool CheckEdge_H4_BUY_9(int tripleAlign, double Ema5_8_Diff_Norm, double MACD_Delta_Norm) {
   return (Ema5_8_Diff_Norm <= -0.031559 && MACD_Delta_Norm >= 0.392367);
}

// Rule #10 [BUY] | Train WR=50.6% | OOS WR=50.5% (1129 trades) | Est OOS PF=1.48
bool CheckEdge_H4_BUY_10(int tripleAlign, double MACD_Delta_Norm, double Stoch_D) {
   return (MACD_Delta_Norm >= 0.392367 && Stoch_D <= 34.000736);
}

// Rule #11 [SELL] | Train WR=56.6% | OOS WR=57.4% (202 trades) | Est OOS PF=1.29
bool CheckEdge_H4_SELL_11(int tripleAlign, double VolRatio, double OBV_Slope_Norm) {
   return (tripleAlign == -1 && VolRatio >= 1.235698 && OBV_Slope_Norm >= 0.397219);
}

// Rule #12 [SELL] | Train WR=56.7% | OOS WR=56.7% (203 trades) | Est OOS PF=1.25
bool CheckEdge_H4_SELL_12(int tripleAlign, double RSI5, double CCI5) {
   return (tripleAlign == -1 && RSI5 <= 93.478264 && CCI5 >= 138.461533);
}

