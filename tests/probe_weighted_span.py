# -*- coding: utf-8 -*-
"""探测各品种「加权指数」日K/分钟K 的实际数据覆盖范围。

直接调 server 内部函数（不走 HTTP），逐品种打印首末日期与根数。
"""
import sys
import collections

sys.path.insert(0, r"C:\Users\gongq\WorkBuddy\2026-10-09-20-14-20\soda-ash-panel")
import server as S

PRODUCTS = ["SA", "RB", "CU", "M", "TA", "AP", "IF", "LC", "SI", "PS"]

print("=" * 88)
print("各品种「加权指数」日K 覆盖范围")
print("=" * 88)
print("%-4s %-8s %-7s %-12s %-12s %s" % ("品种", "名称", "根数", "首日", "末日", "按年分布"))
print("-" * 88)
for p in PRODUCTS:
    try:
        d = S.fetch_weighted_kline(p + "W", "day")
    except Exception as e:
        print("%-4s  ERR %s: %s" % (p, type(e).__name__, e))
        continue
    b = d["bars"]
    if not b:
        print("%-4s  %s  空" % (p, d.get("name", "")))
        continue
    by = collections.Counter(x["t"][:4] for x in b)
    dist = " ".join("%s:%d" % (y, by[y]) for y in sorted(by))
    print("%-4s %-8s %-7d %-12s %-12s %s"
          % (p, d.get("name", ""), len(b), b[0]["t"], b[-1]["t"], dist))

print()
print("=" * 88)
print("各品种「加权指数」分钟K 覆盖范围（根数 / 首日）")
print("=" * 88)
print("%-4s %-9s %-9s %-9s %-9s %-9s %-9s" % ("品种", "1分", "5分", "15分", "30分", "60分", "120分"))
print("-" * 88)
for p in PRODUCTS:
    row = []
    for per in ["1", "5", "15", "30", "60", "120"]:
        try:
            d = S.fetch_weighted_kline(p + "W", per)
            b = d["bars"]
            row.append("%d" % len(b) if b else "0")
        except Exception:
            row.append("-")
    print("%-4s %-9s %-9s %-9s %-9s %-9s %-9s" % (p, *row))
