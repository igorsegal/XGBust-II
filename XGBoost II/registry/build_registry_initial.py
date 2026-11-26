# build_registry_initial.py - ОДНОРАЗОВО: создаёт первую версию rules_registry.json
# (Hedge + 22 правила прототипа). Дальше реестр правится руками или через add_rule.py.
import json, re, sys, os
proto_dir = sys.argv[1] if len(sys.argv) > 1 else r"D:\AHexaTrader\XGBoost-edge\rules"
out = sys.argv[2] if len(sys.argv) > 2 else "rules_registry.json"

hedge = {
  "id": "HEDGE_ENS_01",
  "name": "Hedge: ансамбль из 5 простых сигналов с адаптивными весами",
  "source": {"type": "article", "article_id": 25064, "url": "https://www.mql5.com/en/articles/25064",
             "title": "Hedge (Multiplicative Weights): Blending a Handful of Simple Trading Rules Online", "year": 2026,
             "spec_file": "data_test/specs/25064.json"},
  "status": "implemented_untested",
  "enabled_by_default": True,
  "direction": "both",
  "timeframes": ["H1", "M15"],
  "pairs": ["EURUSD", "GBPUSD", "XAUUSD"],
  "entry_long": "Сумма w_i*v_i >= confidence (по умолчанию 0.20)",
  "entry_short": "Сумма w_i*v_i <= -confidence",
  "exit_rule": "не указан в статье: общий выход тестера (держать hold_bars баров)",
  "stop_rule": "не указан в статье: общий стоп тестера (stop_atr_mult * ATR)",
  "description": "5 экспертов голосуют -1/0/+1 на закрытии бара: пересечение MA, возврат RSI, пробой Bollinger, знак гистограммы MACD, пробой Donchian. Веса w_i стартуют с 1/5 и после каждого бара умножаются на exp(-eta*loss), loss = 0.5 - 0.5*голос*знак_движения_следующего_бара, затем нормируются. eta = sqrt(8*ln(5)/T).",
  "params": {
    "ma_fast": {"type": "int", "default": 10, "min": 2, "max": 200, "note": "период быстрой SMA"},
    "ma_slow": {"type": "int", "default": 50, "min": 3, "max": 500, "note": "период медленной SMA"},
    "rsi_period": {"type": "int", "default": 14, "min": 2, "max": 100, "note": "RSI Уайлдера"},
    "rsi_lower": {"type": "float", "default": 30.0, "min": 1, "max": 49, "note": "ниже: голос +1"},
    "rsi_upper": {"type": "float", "default": 70.0, "min": 51, "max": 99, "note": "выше: голос -1"},
    "bb_period": {"type": "int", "default": 20, "min": 2, "max": 200, "note": "SMA и среднеквадратичное отклонение"},
    "bb_deviation": {"type": "float", "default": 2.0, "min": 0.5, "max": 5.0, "note": "ширина полос"},
    "macd_fast": {"type": "int", "default": 12, "min": 2, "max": 100, "note": ""},
    "macd_slow": {"type": "int", "default": 26, "min": 3, "max": 200, "note": ""},
    "macd_signal": {"type": "int", "default": 9, "min": 2, "max": 100, "note": ""},
    "donchian_period": {"type": "int", "default": 20, "min": 2, "max": 200, "note": ""},
    "donchian_include_current": {"type": "bool", "default": 1, "min": 0, "max": 1, "note": "1 = окно включает текущий бар (как в статье, сигнал почти не срабатывает), 0 = только предыдущие бары"},
    "regret_horizon": {"type": "int", "default": 2000, "min": 100, "max": 100000, "note": "T в формуле eta"},
    "confidence": {"type": "float", "default": 0.20, "min": 0.01, "max": 0.99, "note": "порог ансамбля для входа (допущение судьи)"}
  },
  "assumptions": [
    "Тип MA в статье не назван: взята простая (SMA).",
    "Порог входа 0.20 — допущение судьи, в тексте статьи явной формулы входа по порогу нет.",
    "Знак движения sign(t) берётся как знак (close[t]-close[t-1]); голоса, поданные на баре t-1, оцениваются по движению бара t (причинная версия формулы loss).",
    "Donchian: окно включает текущий бар, как в статье; вариант без текущего бара включается параметром donchian_include_current=0."
  ],
  "implementation": {"language": "cpp", "file": "tester/rules/hedge.h", "factory": "make_hedge"},
  "audit": {"lookahead": "ok_selftest_pending", "duplicate_of": None, "constitution_ok": True,
            "notes": ["Автор сообщает: все 18 тестов статьи завершились убытком; тестируем только исполнимость правила."]},
  "results": []
}

rules = [hedge]
feat_re = r"([A-Za-z0-9_]+) (>=|<=) (-?[0-9.]+)"
for tf in ("H1", "H4"):
    txt = open(os.path.join(proto_dir, f"discovered_edges_{tf}.mqh"), encoding="utf-8-sig").read()
    blocks = re.findall(r"// Rule #(\d+) \[(BUY|SELL)\](.*?)\n(bool CheckEdge_[^\n]*)\n\s*return \((.*?)\);", txt, re.S)
    seen = {}
    for num, dr, meta, sig, cond in blocks:
        m_tr = re.search(r"Train WR=([0-9.]+)%", meta); m_oo = re.search(r"OOS WR=([0-9.]+)% \((\d+) trades\)", meta); m_pf = re.search(r"PF=([0-9.]+)", meta)
        trend = re.search(r"tripleAlign == (-?1)", cond)
        conds = [{"feature": f, "op": o, "threshold": float(v)} for f, o, v in re.findall(feat_re, cond)]
        params = {}
        for k, c in enumerate(conds, 1):
            params[f"thr_{k}"] = {"type": "float", "default": c["threshold"], "min": -1e9, "max": 1e9, "note": f"порог {c['feature']} {c['op']}"}
        key = (dr, tuple((c["feature"], c["op"], c["threshold"]) for c in conds), trend.group(1) if trend else None)
        key2 = (dr, m_oo.group(1) if m_oo else None, m_oo.group(2) if m_oo else None)
        dup = seen.get(key2)
        rid = f"PROTO_{tf}_{dr}_{int(num):02d}"
        seen.setdefault(key2, rid)
        notes = []
        oo_wr = float(m_oo.group(1)) if m_oo else None
        if oo_wr is not None and oo_wr < 56.0:
            notes.append(f"доля побед на OOS {oo_wr}% < 56% (требование AGENTS.md п.3.2); положительное матожидание не доказано: PF в файле оценочный (формула), сделки не проигрывались")
        if any(c["feature"] == "ATR14" for c in conds):
            notes.append("использует сырой ATR14: порог привязан к цене конкретной пары (не scale-invariant)")
        if not trend:
            notes.append("в функции есть параметр tripleAlign, но условие тренда в правиле отсутствует")
        elif dr == "SELL" and trend.group(1) == "-1":
            notes.append("SELL и BUY используют одно условие tripleAlign == -1: проверить смысл флага")
        notes.append("OOS использован для отбора из ~130 тыс. кандидатов: проверка вне выборки не чистая")
        if dup:
            notes.append(f"дубль {dup}: те же число сделок и доля побед на OOS")
        rules.append({
          "id": rid, "name": f"Прототип майнера {tf} {dr} #{num}",
          "source": {"type": "prototype_miner", "file": f"rules/discovered_edges_{tf}.mqh", "tf": tf, "year": 2026},
          "status": "prototype_unconfirmed", "enabled_by_default": False, "direction": "long" if dr == "BUY" else "short",
          "timeframes": [tf], "pairs": ["pooled"],
          "entry_long": " AND ".join(([f"tripleAlign == {trend.group(1)}"] if trend else []) + [f"{c['feature']} {c['op']} thr_{k}" for k, c in enumerate(conds, 1)]) if dr == "BUY" else "",
          "entry_short": " AND ".join(([f"tripleAlign == {trend.group(1)}"] if trend else []) + [f"{c['feature']} {c['op']} thr_{k}" for k, c in enumerate(conds, 1)]) if dr == "SELL" else "",
          "exit_rule": "Target_RR из датасета (фиксированный TP/SL), не воспроизводится тестером OHLC", "stop_rule": "",
          "description": "Правило, найденное перебором пар признаков в mine_v3.cpp на квантованном кэше; признаки в кэше V3 (23 признака), в тестере OHLC не реализованы.",
          "params": params, "assumptions": [],
          "implementation": None,
          "metrics_claimed": {"train_wr": float(m_tr.group(1)) if m_tr else None, "oos_wr": oo_wr, "oos_trades": int(m_oo.group(2)) if m_oo else None, "est_oos_pf": float(m_pf.group(1)) if m_pf else None},
          "audit": {"lookahead": "unchecked", "duplicate_of": dup, "constitution_ok": not (oo_wr is not None and oo_wr < 56.0), "notes": notes},
          "results": []
        })

reg = {
  "registry_version": 1,
  "description": "Реестр торговых правил XGBoost-edge. Критерии и издержки заморожены 2026-11-24 (claude/xgb_rules_frozen.md).",
  "defaults": {
    "exits": {"hold_bars": 24, "stop_atr_mult": 2.0, "atr_period": 14},
    "costs": {"commission_per_lot_usd": 7, "lot_units": 100000, "spread": "по бару из файла истории"},
    "split": {"years": 5, "train_years": 3, "val_years": 1, "clean_years": 1},
    "criteria": {"min_trades": 100, "min_profit_factor": 1.3, "net_profit_positive": True}
  },
  "rules": rules
}
json.dump(reg, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("правил:", len(rules), "->", out)
