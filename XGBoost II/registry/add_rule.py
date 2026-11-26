#!/usr/bin/env python3
"""add_rule.py - добавить новое правило в реестр из шаблона.
Использование:
  python add_rule.py НОВЫЙ_ID "Название правила"          - правило с кодом на C++ (шаблон RULE_TEMPLATE.json)
  python add_rule.py НОВЫЙ_ID "Название правила" --expr   - правило строкой условия и списком индикаторов (шаблон RULE_TEMPLATE_EXPR.json), код не нужен
Потом откройте rules_registry.json, найдите запись и заполните условия, параметры, источник;
затем: python validate_registry.py"""
import json, sys, os, copy
here = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if a != "--expr"]
if len(args) < 2: print(__doc__); sys.exit(2)
rid, name = args[0], args[1]
tpl = "RULE_TEMPLATE_EXPR.json" if "--expr" in sys.argv else "RULE_TEMPLATE.json"
reg_path = os.path.join(here, "rules_registry.json")
reg = json.load(open(reg_path, encoding="utf-8-sig"))
if any(r["id"] == rid for r in reg["rules"]): print("Правило с таким id уже есть:", rid); sys.exit(1)
t = json.load(open(os.path.join(here, tpl), encoding="utf-8-sig"))
t["id"], t["name"] = rid, name
reg["rules"].append(copy.deepcopy(t))
json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Добавлено:", rid, "(статус spec_ready, выключено). Заполните запись и запустите validate_registry.py")
