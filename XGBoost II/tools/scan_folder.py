# -*- coding: utf-8 -*-
"""Опись папки с данными. ТОЛЬКО ЧТЕНИЕ: файлы не меняются, не перемещаются и не удаляются.
Единственное, что создаётся, - отчёт <папка>\\_opis\\opis.json.
Находит точные копии (по содержимому) и сравнивает файлы баров XFBAR001 между собой."""
import hashlib
import json
import os
import struct
import sys
import time
from collections import defaultdict

try:
    import numpy as np
except ImportError:
    np = None

SKIP = "_opis"


def long_path(p):
    p = os.path.abspath(p)
    return "\\\\?\\" + p if os.name == "nt" and not p.startswith("\\\\") else p


def walk(root, errors, links):
    stack = [""]
    while stack:
        rel = stack.pop()
        try:
            entries = list(os.scandir(os.path.join(root, rel) if rel else root))
        except OSError as e:
            errors.append([rel, str(e)])
            continue
        for e in entries:
            r = os.path.join(rel, e.name) if rel else e.name
            try:
                if e.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(e.path)):
                    links.append(r)
                elif e.is_dir(follow_symlinks=False):
                    if r != SKIP:
                        stack.append(r)
                else:
                    s = e.stat(follow_symlinks=False)
                    yield {"p": r, "s": s.st_size, "m": int(s.st_mtime)}
            except OSError as ex:
                errors.append([r, str(ex)])


def digest(path, size, quick):
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        if quick and size > 131072:
            h.update(f.read(65536))
            f.seek(-65536, 2)
            h.update(f.read(65536))
        else:
            while block := f.read(4 << 20):
                h.update(block)
    return h.hexdigest()


def peek(path, item):
    """Первые байты: заголовок XFBAR001 или первые и последняя строки текста."""
    name = item["p"].lower()
    with open(path, "rb") as f:
        head = f.read(128)
        if head[:8] == b"XFBAR001" and len(head) >= 60:
            _, _, period, _, _, n, first, last, sl = struct.unpack_from("<iiiidqqqi", head, 8)
            item["xf"] = {"sym": head[60:60 + max(0, min(sl, 64))].decode("utf-8", "replace"),
                          "period": period, "n": n, "first": first, "last": last}
        elif name.endswith((".csv", ".txt", ".md", ".hst")) and not name.endswith(".hst"):
            f.seek(0)
            start = f.read(600).decode("utf-8", "replace").splitlines()[:3]
            f.seek(max(0, item["s"] - 400))
            end = f.read().decode("utf-8", "replace").strip().splitlines()[-1:]
            item["text"] = {"head": [x[:200] for x in start], "tail": [x[:200] for x in end]}
        elif item["s"]:
            item["magic"] = head[:8].decode("latin-1")


def load_bars(path):
    with open(path, "rb") as f:
        b = f.read()
    sl = struct.unpack_from("<i", b, 56)[0]
    dt = np.dtype([("t", "<i8"), ("o", "<f8"), ("h", "<f8"), ("l", "<f8"), ("c", "<f8"),
                   ("tv", "<i8"), ("sp", "<i4"), ("rv", "<i8")])
    n = (len(b) - 60 - sl) // 60
    return np.frombuffer(b, dt, n, 60 + sl)


def compare_bars(root, items):
    """Каждый файл одной пары и периода сравнивается с самым большим: сколько баров в нём есть."""
    groups = defaultdict(list)
    for it in items:
        if "xf" in it:
            groups[(it["xf"]["sym"], it["xf"]["period"])].append(it)
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=lambda x: -x["s"])
        try:
            base = load_bars(os.path.join(root, g[0]["p"]))
        except Exception as e:
            g[0]["cmp_error"] = str(e)
            continue
        order = np.argsort(base["t"], kind="stable")
        base = base[order]
        for it in g[1:]:
            try:
                a = load_bars(os.path.join(root, it["p"]))
                i = np.minimum(np.searchsorted(base["t"], a["t"]), max(len(base) - 1, 0))
                found = base["t"][i] == a["t"] if len(base) else np.zeros(len(a), bool)
                same = found.copy()
                for k in "ohlc":
                    same[found] &= np.abs(a[k][found] - base[k][i[found]]) < 1e-9
                it["cmp"] = {"with": g[0]["p"], "bars": len(a), "time_found": int(found.sum()),
                             "ohlc_same": int(same.sum())}
            except Exception as e:
                it["cmp_error"] = str(e)


def main(folder):
    root = long_path(folder)
    if not os.path.isdir(root):
        print("NO FOLDER", folder)
        return 1
    errors, links = [], []
    items = list(walk(root, errors, links))
    total = sum(x["s"] for x in items)
    print(f"files: {len(items)}, size: {total / 1024 ** 3:.2f} GB", flush=True)
    by_size = defaultdict(list)
    for it in items:
        try:
            peek(os.path.join(root, it["p"]), it)
        except Exception as e:
            errors.append([it["p"], str(e)])
        if it["s"]:
            by_size[it["s"]].append(it)
    candidates = [g for g in by_size.values() if len(g) > 1]
    second = []
    print("step 1 of 3: quick check", flush=True)
    for g in candidates:
        quick = defaultdict(list)
        for it in g:
            try:
                quick[digest(os.path.join(root, it["p"]), it["s"], True)].append(it)
            except OSError as e:
                errors.append([it["p"], str(e)])
        second += [x for x in quick.values() if len(x) > 1]
    todo = sum(x["s"] for g in second for x in g)
    print(f"step 2 of 3: full check of possible copies, {todo / 1024 ** 3:.2f} GB", flush=True)
    done, shown = 0, time.time()
    for g in second:
        for it in g:
            try:
                it["hash"] = digest(os.path.join(root, it["p"]), it["s"], False)
            except OSError as e:
                errors.append([it["p"], str(e)])
            done += it["s"]
            if time.time() - shown > 10:
                shown = time.time()
                print(f"  {done / todo:.0%}", flush=True)
    print("step 3 of 3: compare bar files", flush=True)
    if np is not None:
        compare_bars(root, items)
    out = os.path.join(root, SKIP)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "opis.json"), "w", encoding="utf-8") as f:
        json.dump({"root": folder, "files": items, "links": links, "errors": errors,
                   "numpy": np is not None}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"errors: {len(errors)}")
    print("SCAN OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else r"D:\AHexaTrader\1DataFiles"))
