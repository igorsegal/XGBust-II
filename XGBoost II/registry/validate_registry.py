#!/usr/bin/env python3
"""validate_registry.py - проверка реестра правил, справочника индикаторов и конфигов тестов.
Использование:  python validate_registry.py [rules_registry.json] [configs\\*.json ...]
Код возврата 0 = всё в порядке, 1 = есть ошибки. Предупреждения (WARN) не ломают проверку."""
import json, sys, os, glob, re

STATUSES = {"spec_ready", "implemented_untested", "tested_pass", "tested_fail", "dev_pass", "prototype_unconfirmed", "rejected", "example"}
PRICE_FIELDS = {"open", "high", "low", "close", "spread"}
KEYWORDS = {"AND", "OR", "NOT"}
FUNCS = {"abs": 1, "min": 2, "max": 2, "prev": 2, "crossup": 2, "crossdown": 2}
errors, warns = [], []
def err(m): errors.append(m)
def warn(m): warns.append(m)

def load(p):
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)

# ---------- разбор строки условия (отдельная реализация, независимая от C++) ----------
TOK = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|[<>+\-*/(),]))")

def tokenize(s):
    pos, out = 0, []
    s = s.rstrip()
    while pos < len(s):
        m = TOK.match(s, pos)
        if not m or m.end() == pos: raise ValueError(f"недопустимый символ '{s[pos:].lstrip()[:1]}'")
        pos = m.end()
        if m.group(1) is not None: out.append(("num", float(m.group(1))))
        elif m.group(2) is not None: out.append(("id", m.group(2)))
        else: out.append(("sym", m.group(3)))
    return out

class P:
    def __init__(self, toks, names):
        self.t, self.i, self.names, self.used = toks, 0, names, set()
    def peek(self): return self.t[self.i] if self.i < len(self.t) else ("end", None)
    def kw(self, w): k, v = self.peek(); return k == "id" and v.upper() == w
    def sym(self, w): k, v = self.peek(); return k == "sym" and v == w
    def or_(self):
        self.and_()
        while self.kw("OR"): self.i += 1; self.and_()
    def and_(self):
        self.not_()
        while self.kw("AND"): self.i += 1; self.not_()
    def not_(self):
        if self.kw("NOT"): self.i += 1; self.not_()
        else: self.cmp()
    def cmp(self):
        self.add()
        for o in ("<=", ">=", "==", "!=", "<", ">"):
            if self.sym(o):
                self.i += 1; self.add()
                if any(self.sym(x) for x in ("<", ">", "<=", ">=", "==", "!=")):
                    raise ValueError("цепочки сравнений a < b < c не поддерживаются, используйте AND")
                return
    def add(self):
        self.mul()
        while self.sym("+") or self.sym("-"): self.i += 1; self.mul()
    def mul(self):
        self.un()
        while self.sym("*") or self.sym("/"): self.i += 1; self.un()
    def un(self):
        if self.sym("-"): self.i += 1; self.un()
        else: self.prim()
    def prim(self):
        k, v = self.peek()
        if k == "num": self.i += 1; return
        if self.sym("("):
            self.i += 1; self.or_()
            if not self.sym(")"): raise ValueError("нет закрывающей скобки")
            self.i += 1; return
        if k == "id":
            self.i += 1
            if self.sym("("):
                self.i += 1; args = []
                if not self.sym(")"):
                    while True:
                        st = self.i; self.or_(); args.append(self.t[st:self.i])
                        if self.sym(","): self.i += 1; continue
                        break
                if not self.sym(")"): raise ValueError(f"нет закрывающей скобки у функции {v}")
                self.i += 1
                if v not in FUNCS: raise ValueError(f"неизвестная функция: {v}")
                if len(args) != FUNCS[v]: raise ValueError(f"функция {v}: неверное число аргументов")
                if v == "prev":
                    a = args[1]
                    if not (len(a) == 1 and a[0][0] == "num" and a[0][1] >= 0 and a[0][1] == int(a[0][1]) and a[0][1] <= 5000):
                        raise ValueError("prev(x, n): n должно быть целым числом от 0 до 5000")
                return
            if v.upper() in KEYWORDS: raise ValueError(f"неожиданное слово {v}")
            if v not in self.names: raise ValueError(f"неизвестное имя в условии: {v}")
            self.used.add(v); return
        raise ValueError("ошибка в условии: ожидалось число, имя или скобка")

def check_expr(rid, field, text, names):
    try:
        p = P(tokenize(text), names); p.or_()
        if p.peek()[0] != "end": raise ValueError(f"лишнее в конце условия: {p.peek()[1]}")
        return p.used
    except ValueError as e:
        err(f"{rid}.{field}: {e}"); return set()

# ---------- справочник индикаторов ----------
def check_catalog(path):
    cat = load(path); ids = set(); byid = {}
    for i in cat.get("indicators", []):
        iid = i.get("id", "?")
        if iid in ids: err(f"справочник: повторяющийся индикатор {iid}")
        ids.add(iid); byid[iid] = i
        if i.get("status") not in ("implemented", "planned"): err(f"справочник {iid}: статус должен быть implemented или planned")
        if i.get("default_output") not in i.get("outputs", []): err(f"справочник {iid}: default_output не входит в outputs")
        for k, p in i.get("params", {}).items():
            if not all(x in p for x in ("type", "default", "min", "max")): err(f"справочник {iid}.{k}: нужны type/default/min/max"); continue
            if not (p["min"] <= p["default"] <= p["max"]): err(f"справочник {iid}.{k}: значение по умолчанию вне диапазона")
    return cat, byid

def resolve_inputs(r, rule_params, cat, where):
    """Проверка inputs правила при заданных значениях параметров правила. Возвращает множество имён входов."""
    names = set()
    for k, inp in enumerate(r.get("inputs", [])):
        nm = inp.get("name", "?"); tag = f"{where}.inputs[{nm}]"
        if nm in names: err(f"{tag}: повторяющееся имя входа")
        if nm in PRICE_FIELDS or nm in rule_params or nm in FUNCS or nm.upper() in KEYWORDS: err(f"{tag}: имя совпадает с ценой, параметром, функцией или словом AND/OR/NOT")
        names.add(nm)
        ind = cat["byid"].get(inp.get("indicator"))
        if not ind: err(f"{tag}: индикатора {inp.get('indicator')} нет в справочнике"); continue
        if ind["status"] != "implemented": err(f"{tag}: индикатор {ind['id']} не реализован (planned)"); continue
        out = inp.get("output", ind["default_output"])
        if out not in ind["outputs"]: err(f"{tag}: у {ind['id']} нет выхода {out}; есть: {', '.join(ind['outputs'])}")
        if inp.get("tf", "H1") not in cat["data"]["timeframes"]: err(f"{tag}: неизвестный таймфрейм {inp.get('tf')}")
        if inp.get("source", "close") not in cat["data"]["sources"]: err(f"{tag}: неизвестный источник цены {inp.get('source')}")
        for pk, pv in inp.get("params", {}).items():
            pd = ind["params"].get(pk)
            if not pd: err(f"{tag}: у {ind['id']} нет параметра {pk}"); continue
            if isinstance(pv, str):
                if not pv.startswith("$") or pv[1:] not in rule_params: err(f"{tag}.{pk}: ссылка {pv} не указывает на параметр правила"); continue
                pv = rule_params[pv[1:]]
            if not (pd["min"] <= pv <= pd["max"]): err(f"{tag}.{pk}={pv} вне диапазона справочника [{pd['min']}, {pd['max']}]")
            if pd["type"] == "int" and int(pv) != pv: err(f"{tag}.{pk}={pv} должно быть целым")
    return names

def check_registry(path, cat):
    base = os.path.dirname(os.path.abspath(path))
    reg = load(path)
    try:
        import jsonschema
        sp = os.path.join(base, "registry.schema.json")
        if os.path.exists(sp):
            for e in jsonschema.Draft7Validator(load(sp)).iter_errors(reg):
                err("схема: " + "/".join(map(str, e.absolute_path)) + ": " + e.message[:120])
    except ImportError:
        warn("модуль jsonschema не установлен: проверка по схеме пропущена, остальные проверки выполнены")
    ids = set()
    for r in reg.get("rules", []):
        rid = r.get("id", "?")
        if rid in ids: err(f"{rid}: повторяющийся id")
        ids.add(rid)
        if not re.fullmatch(r"[A-Z0-9_]+", rid): err(f"{rid}: id должен состоять из A-Z, 0-9, _")
        if r.get("status") not in STATUSES: err(f"{rid}: неизвестный статус {r.get('status')}")
        for k, p in r.get("params", {}).items():
            if not all(x in p for x in ("type", "default", "min", "max")): err(f"{rid}.{k}: нужны type/default/min/max"); continue
            if not (p["min"] <= p["default"] <= p["max"]): err(f"{rid}.{k}: значение по умолчанию {p['default']} вне диапазона [{p['min']}, {p['max']}]")
            if p["type"] == "int" and int(p["default"]) != p["default"]: err(f"{rid}.{k}: тип int, а значение {p['default']}")
        impl = r.get("implementation")
        kind = (impl or {}).get("kind", "cpp") if impl else None
        if impl and kind in ("cpp", "strategy", "signals"):
            f = os.path.join(base, impl.get("file", ""))
            if not os.path.exists(f): err(f"{rid}: файл реализации не найден: {impl.get('file')}")
        if kind == "expr":
            if not r.get("entry_long_expr") and not r.get("entry_short_expr"): err(f"{rid}: правило expr без entry_long_expr и entry_short_expr")
            dflt = {k: p["default"] for k, p in r.get("params", {}).items()}
            inames = resolve_inputs(r, dflt, cat, rid)
            names = set(PRICE_FIELDS) | set(dflt) | inames
            for fld in ("entry_long_expr", "entry_short_expr"):
                if r.get(fld): check_expr(rid, fld, r[fld], names)
            if r.get("direction") == "long" and r.get("entry_short_expr"): err(f"{rid}: направление long, но задан entry_short_expr")
            if r.get("direction") == "short" and r.get("entry_long_expr"): err(f"{rid}: направление short, но задан entry_long_expr")
        elif r.get("inputs") or r.get("entry_long_expr") or r.get("entry_short_expr"):
            err(f"{rid}: inputs и условия-строки допустимы только при implementation.kind = expr")
        if r.get("enabled_by_default") and not impl: err(f"{rid}: включено по умолчанию, но реализации нет")
        if r.get("status") == "prototype_unconfirmed" and r.get("enabled_by_default"): err(f"{rid}: неподтверждённый прототип нельзя включать по умолчанию")
        if r.get("status") == "example" and r.get("enabled_by_default"): err(f"{rid}: учебный пример нельзя включать по умолчанию")
        if r.get("status") in ("tested_pass", "dev_pass") and not r.get("results"): err(f"{rid}: статус {r.get('status')} без записей results")
        dup = r.get("audit", {}).get("duplicate_of")
        if dup and dup not in {x.get("id") for x in reg["rules"]}: err(f"{rid}: duplicate_of ссылается на несуществующее правило {dup}")
        if not r.get("entry_long") and not r.get("entry_short"): warn(f"{rid}: нет условия входа")
    return reg

def check_config(path, reg, cat):
    c = load(path); rules = {r["id"]: r for r in reg["rules"]}; fn = os.path.basename(path)
    for rid, rc in c.get("rules", {}).items():
        if rid not in rules: err(f"{fn}: правила {rid} нет в реестре"); continue
        r = rules[rid]
        if rc.get("enabled") and not r.get("implementation"): err(f"{fn}: {rid} включено, но реализации нет")
        vals = {k: p["default"] for k, p in r.get("params", {}).items()}
        for k, v in rc.get("params", {}).items():
            p = r["params"].get(k)
            if not p: err(f"{fn}: {rid}: параметра {k} нет в реестре"); continue
            if not (p["min"] <= v <= p["max"]): err(f"{fn}: {rid}.{k}={v} вне диапазона [{p['min']}, {p['max']}]")
            vals[k] = v
        if rc.get("enabled") and (r.get("implementation") or {}).get("kind") == "expr":
            resolve_inputs(r, vals, cat, f"{fn}:{rid}")
    for k in ("data", "period", "costs", "exits", "criteria", "test_name"):
        if k not in c: err(f"{fn}: нет раздела {k}")
    per = c.get("period", {})
    for k in ("train_months", "test_months", "step_months"):
        if not (isinstance(per.get(k), int) and per[k] >= 1): err(f"{fn}: period.{k} должно быть целым от 1")
    if per.get("step_months") != per.get("test_months"): err(f"{fn}: сдвиг (step_months) должен быть равен проверке (test_months)")
    months = [per.get(k) for k in ("dev_from", "exam_from", "exam_to")]
    if not all(isinstance(m, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m) for m in months):
        err(f"{fn}: period.dev_from, exam_from, exam_to должны быть в виде ГГГГ-ММ")
    elif not months[0] < months[1] <= months[2]: err(f"{fn}: нужно dev_from < exam_from <= exam_to")
    pair = c.get("data", {}).get("pair", "")
    if not (len(pair) == 6 and (pair.endswith("USD") or pair.startswith("USD"))): err(f"{fn}: инструмент {pair}: комиссия считается только для инструментов с USD")
    lot = 100 if pair.startswith("XAU") else 100000
    if c.get("costs", {}).get("lot_units", lot) != lot: err(f"{fn}: lot_units не соответствует инструменту {pair}")

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    reg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "rules_registry.json")
    cat, byid = check_catalog(os.path.join(os.path.dirname(os.path.abspath(reg_path)), "indicators_catalog.json"))
    cat = {"byid": byid, "data": cat}
    reg = check_registry(reg_path, cat)
    cfgs = sys.argv[2:] or glob.glob(os.path.join(here, "configs", "*.json"))
    for c in cfgs: check_config(c, reg, cat)
    nimpl = sum(1 for i in byid.values() if i["status"] == "implemented")
    print(f"правил в реестре: {len(reg['rules'])}, конфигов проверено: {len(cfgs)}, индикаторов в справочнике: {len(byid)} (реализовано {nimpl})")
    for w in warns: print("WARN:", w)
    for e in errors: print("ОШИБКА:", e)
    print("ИТОГ:", "ОШИБКИ" if errors else "OK")
    sys.exit(1 if errors else 0)
