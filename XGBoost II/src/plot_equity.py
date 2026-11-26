import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
df = pd.read_csv("rules/oos_equity_curve.csv")
df["Date"] = pd.to_datetime(df["Date"])
start_bal = 1000.0
final_bal = df["Balance"].iloc[-1]
net_pct = (final_bal - start_bal) / start_bal * 100.0
max_dd = df["DrawdownPct"].max()
trades = len(df) - 1
wins = df["Win"].iloc[1:].sum()
wr = wins / max(1, trades) * 100.0
gp = df[df["PnL_USD"] > 0]["PnL_USD"].sum()
gl = abs(df[df["PnL_USD"] < 0]["PnL_USD"].sum())
pf = gp / max(0.01, gl)
plt.style.use("dark_background")
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), gridspec_kw={"height_ratios": [3.2, 1]}, sharex=True)
fig.patch.set_facecolor("#0f1419")
ax1.set_facecolor("#151c24")
ax2.set_facecolor("#151c24")
ax1.plot(df["Date"], df["Balance"], color="#00e676", linewidth=2.0, label="Баланс портфеля ($)")
ax1.fill_between(df["Date"], start_bal, df["Balance"], color="#00e676", alpha=0.12)
ax1.axhline(start_bal, color="#8899a6", linestyle="--", linewidth=1.0, label="Стартовый депозит ($1,000)")
title = (
    f"XGBoost-edge V3 — Out-of-Sample Тест портфеля ({df['Date'].iloc[0].strftime('%Y-%m-%d')} — {df['Date'].iloc[-1].strftime('%Y-%m-%d')})\n"
    f"Старт: $1,000  |  Итог: ${final_bal:,.2f} (+{net_pct:,.1f}%)  |  Сделок: {trades}  |  WinRate: {wr:.1f}%  |  PF: {pf:.2f}  |  MaxDD: {max_dd:.2f}%"
)
ax1.set_title(title, fontsize=12, fontweight="bold", color="#ffffff", pad=12)
ax1.set_ylabel("Баланс ($)", fontsize=11, color="#cfd8dc")
ax1.grid(True, color="#263238", linestyle=":", linewidth=0.8)
ax1.legend(loc="upper left", frameon=True, facecolor="#1c2530", edgecolor="#37474f")
ax2.fill_between(df["Date"], 0, -df["DrawdownPct"], color="#ff5252", alpha=0.45)
ax2.plot(df["Date"], -df["DrawdownPct"], color="#ff5252", linewidth=1.1)
ax2.set_ylabel("Просадка (%)", fontsize=10, color="#cfd8dc")
ax2.set_xlabel("Дата (строгий Out-of-Sample, не участвовавший в обучении)", fontsize=11, color="#cfd8dc")
ax2.grid(True, color="#263238", linestyle=":", linewidth=0.8)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig("rules/oos_equity_curve.png", dpi=160)
print("Saved chart to rules/oos_equity_curve.png")
