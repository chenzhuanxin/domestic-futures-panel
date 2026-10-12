# -*- coding: utf-8 -*-
"""探针：加权分钟K「历史拼接」可行性实测。

目的（先测量再定阈值，不靠猜）：
  1. 某品种各月份合约的分钟K窗口到底有多长（不同周期差别巨大）
  2. 把全部历史合约的分钟K按时间戳求并集后，**真实的断层分布**是什么样
  3. 60/120 分钟是否真能拼成连续历史；5/15 分钟能拼到哪一年

用法：
    C:/Python314/python.exe tests/probe_minute_stitch.py SA 5,15,60,120
"""
from __future__ import annotations

import collections
import datetime as dt
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as S                                                   # noqa: E402

YEARS_BACK = 9
WORKERS = 12


def fetch_bars(code: str, period: str):
    try:
        return code, S.fetch_kline(code, period)["bars"]
    except Exception:                                                # noqa: BLE001
        return code, []


def analyze(product: str, period: str) -> None:
    codes = S.all_contract_codes(product, years_back=YEARS_BACK)
    print("\n" + "=" * 78)
    print("品种 %s  周期 %s  枚举合约 %d 个" % (product, period, len(codes)))
    print("=" * 78)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda c: fetch_bars(c, period), codes))

    live = [(c, b) for c, b in results if b]
    empty = [c for c, b in results if not b]
    print("有数据合约 %d 个 / 空 %d 个" % (len(live), len(empty)))

    # 每个合约的窗口长度
    spans = []
    for c, b in live:
        f = dt.datetime.strptime(b[0]["t"], "%Y-%m-%d %H:%M:%S")
        l = dt.datetime.strptime(b[-1]["t"], "%Y-%m-%d %H:%M:%S")
        spans.append((c, len(b), (l - f).days, b[0]["t"], b[-1]["t"]))
    spans.sort(key=lambda x: x[3])
    print("\n-- 窗口长度（按起始时间排序，抽样显示）--")
    print("  %-9s %6s %8s  %-20s %-20s" % ("合约", "根数", "覆盖天", "首", "末"))
    for row in spans[:6]:
        print("  %-9s %6d %8d  %-20s %-20s" % row)
    if len(spans) > 12:
        print("  ...（省略 %d 行）..." % (len(spans) - 12))
    for row in spans[-6:]:
        print("  %-9s %6d %8d  %-20s %-20s" % row)

    # 并集时间轴 + 断层
    stamps = sorted({b["t"] for _, bars in live for b in bars})
    if len(stamps) < 2:
        print("\n时间戳不足，跳过")
        return
    dts = [dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in stamps]
    gaps = [(dts[i + 1] - dts[i]).total_seconds() / 86400.0
            for i in range(len(dts) - 1)]

    print("\n-- 并集时间轴 --")
    print("  总根数 %d   起点 %s   终点 %s" % (len(stamps), stamps[0], stamps[-1]))

    # 按年统计根数
    byyear = collections.Counter(s[:4] for s in stamps)
    print("  按年根数: " + "  ".join("%s:%d" % (y, byyear[y]) for y in sorted(byyear)))

    # 断层直方图（只列 > 1 天的，日内/隔夜/周末属正常）
    hist = collections.Counter()
    for g in gaps:
        if g <= 1:
            hist["≤1天(日内/隔夜)"] += 1
        elif g <= 4:
            hist["1~4天(周末)"] += 1
        elif g <= 12:
            hist["4~12天(长假)"] += 1
        elif g <= 45:
            hist["12~45天"] += 1
        else:
            hist[">45天"] += 1
    print("\n-- 相邻根间隔分布 --")
    for k in ("≤1天(日内/隔夜)", "1~4天(周末)", "4~12天(长假)",
              "12~45天", ">45天"):
        if hist[k]:
            print("  %-16s %6d 处" % (k, hist[k]))

    big = [(stamps[i], stamps[i + 1], gaps[i]) for i in range(len(gaps))
           if gaps[i] > 12]
    if big:
        print("\n-- 12 天以上的大断层（最多列 25 处）--")
        for a, b, g in big[:25]:
            print("    %s  →  %s   (%.1f 天)" % (a, b, g))
        if len(big) > 25:
            print("    ...（共 %d 处）" % len(big))
    else:
        print("\n  ✓ 无 12 天以上断层：该周期可拼成连续历史")

    # 以「最新一根」为终点、按不同容差截取连续段
    for tol in (4, 12, 30):
        n = 1
        for i in range(len(gaps) - 1, -1, -1):
            if gaps[i] > tol:
                break
            n += 1
        print("  容差 %2d 天 → 尾部连续段 %d 根（自 %s）"
              % (tol, n, stamps[len(stamps) - n]))


if __name__ == "__main__":
    prod = (sys.argv[1] if len(sys.argv) > 1 else "SA").upper()
    periods = (sys.argv[2] if len(sys.argv) > 2 else "5,15,60,120").split(",")
    for p in periods:
        analyze(prod, p.strip())
