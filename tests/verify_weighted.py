# -*- coding: utf-8 -*-
"""加权指数全品种校验 + 算法正确性交叉验证。

用法（需先启动服务）：
    python tests/verify_weighted.py [base_url]
"""
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8686"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

ok = fail = 0
fails = []


def api(path, **params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with opener.open(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [PASS] %s  %s" % (name, ("→ " + detail) if detail else ""))
    else:
        fail += 1
        fails.append(name)
        print("  [FAIL] %s  → %s" % (name, detail))


def manual_weighted(items, mode="oi"):
    """独立实现一遍加权（不复用服务端代码），用于交叉验证。"""
    rows = []
    for it in items:
        c = it["code"]
        if c.endswith("0") or c.endswith("W"):
            continue
        w = float(it["volume"] if mode == "vol" else it["oi"] or 0)
        if w <= 0 or not it["last"]:
            continue
        rows.append((it["last"], it["presettle"], w, it["open"], it["high"], it["low"]))
    tot = sum(r[2] for r in rows)
    if not rows or tot <= 0:
        return None
    return {
        "last": sum(r[0] * r[2] for r in rows) / tot,
        "presettle": sum(r[1] * r[2] for r in rows) / tot,
        "open": sum(r[3] * r[2] for r in rows) / tot,
        "high": sum(r[4] * r[2] for r in rows) / tot,
        "low": sum(r[5] * r[2] for r in rows) / tot,
    }


def check_product(p):
    try:
        d = api("/api/symbols", product=p)["data"]
    except Exception as exc:                            # noqa: BLE001
        return (p, "EXC %s" % exc, None, None)
    w = next((it for it in d["items"] if it.get("isWeighted")), None)
    if not d["items"]:
        return (p, "无合约", None, None)
    if not w:
        return (p, "无加权行", None, None)
    # 加权行必须置顶
    top_ok = d["items"][0].get("isWeighted")
    man = manual_weighted(d["items"])
    return (p, None, (w, man, top_ok, d["count"]), d)


def main():
    print("=" * 72)
    print("  加权指数全品种校验  ·  %s" % BASE)
    print("=" * 72)

    print("\n========== 1. 全品种加权行生成 ==========")
    prods = api("/api/products")["data"]["groups"]
    codes = [it["product"] for g in prods for it in g["items"] if it.get("tradeable")]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check_product, codes))
    bad = [(p, err) for p, err, _, _ in results if err]
    check("全部 %d 个在交易品种都能生成加权行" % len(codes), not bad,
          ("; ".join("%s:%s" % b for b in bad[:8]) if bad else "全部正常"))

    print("\n========== 2. 加权行必须置顶 ==========")
    notop = [p for p, err, r, _ in results if not err and r and not r[2]]
    check("所有品种加权行都排在第 1 位", not notop, ",".join(notop) or "全部正常")

    print("\n========== 3. 算法自洽性（components 快照 vs 加权结果） ==========")
    # 注意：不能拿「另一次请求的 items」跟加权值比 —— 两次请求之间行情会跳动。
    # 正确做法是用加权行自带的 components（服务端算加权时用的那份快照）反推。
    mism = []
    for p, err, r, _ in results:
        if err or not r:
            continue
        w = r[0]
        comp = w.get("components") or []
        if len(comp) < 2:
            continue
        recon = sum(c["weight"] * c["last"] for c in comp)
        s = sum(c["weight"] for c in comp)
        # 用相对容差：高价品种（如锡 39 万）用绝对容差会误判
        tol = max(0.05, abs(w["last"]) * 1e-5)
        if abs(recon - w["last"]) > tol or abs(s - 1.0) > 0.01:
            mism.append("%s 反推%.2f/值%.2f 权重和%.4f" % (p, recon, w["last"], s))
    check("加权值 = Σ(权重×成分最新价)，且权重归一", not mism,
          ("; ".join(mism[:8]) if mism else "全部自洽"))

    print("\n========== 4. 加权价必须落在成分价格区间内 ==========")
    out = []
    for p, err, r, dd in results:
        if err or not r or not dd:
            continue
        w = r[0]
        prices = [it["last"] for it in dd["items"]
                  if not it.get("isWeighted") and not it["code"].endswith("0") and it["last"]]
        if prices and not (min(prices) - 0.01 <= w["last"] <= max(prices) + 0.01):
            out.append("%s 加权%.2f 不在[%.2f,%.2f]" % (p, w["last"], min(prices), max(prices)))
    check("加权价介于成分合约最低价与最高价之间", not out,
          ("; ".join(out[:6]) if out else "全部合理"))

    print("\n========== 5. 权重归一与成分数 ==========")
    bad2 = []
    for p, err, r, _ in results:
        if err or not r:
            continue
        w = r[0]
        comp = w.get("components") or []
        s = sum(c["weight"] for c in comp)
        if comp and abs(s - 1.0) > 0.01:
            bad2.append("%s 权重和%.4f" % (p, s))
    check("各品种成分权重之和 ≈ 1", not bad2, ("; ".join(bad2[:6]) if bad2 else "全部 ≈1"))

    print("\n========== 6. 加权分时 / 加权K线接口 ==========")
    for p in ["SA", "RB", "IF", "AU", "M"]:
        try:
            ts = api("/api/timeshare", symbol=p + "W")["data"]
            k = api("/api/kline", symbol=p + "W", period="day")["data"]
            check("%s 加权分时+K线可用" % p,
                  len(ts["points"]) > 0 and len(k["bars"]) > 0,
                  "分时 %d 点 / 日K %d 根" % (len(ts["points"]), len(k["bars"])))
        except Exception as exc:                        # noqa: BLE001
            check("%s 加权分时+K线可用" % p, False, "%s: %s" % (type(exc).__name__, exc))

    print("\n========== 7. 加权日K 必须是全量历史 ==========")
    # 历史日K 必须用「逐根持仓量动态加权」并枚举全部月份合约：
    # 若误用当前 Top-N 静态权重，会漏掉当时的当月合约，K线根数与成交量都会严重缩水
    # （实测修复前 SA 仅 216 根、2026-03 成交量被低估 200 倍；修复后 1100+ 根）。
    MIN_BARS = 700          # 近 3 年是活跃品种，日K 至少应有 700 根
    short = []
    vol_bad = []
    for p in ["SA", "RB", "M", "CU", "AU"]:
        try:
            k = api("/api/kline", symbol=p + "W", period="day")["data"]
            bars = k["bars"]
            if len(bars) < MIN_BARS:
                short.append("%s 仅 %d 根" % (p, len(bars)))
            # 修复前的典型症状：历史段漏掉了当时的当月合约，成交量被低估 3~4 个数量级
            # （SA 修复前 2026-03 仅 5452 vs 今 178 万；CU 修复前 2022-03 仅 79 vs 应 14 万）。
            # 判据：近一年中位量的 1% —— 只要历史段没有出现"量级塌陷"即视为正常。
            # 注意不能用"首根 vs 末根"：品种上市初期成交量本身就小，属正常。
            if len(bars) > 260:
                recent = sorted(x for x in (b.get("v") or 0 for b in bars[-250:]) if x > 0)
                if recent:
                    med = recent[len(recent) // 2]
                    # 逐段扫描：把历史切成 120 根一段，任何一段中位量都不应低于基准 1%
                    seg_bad = 0
                    for s0 in range(0, len(bars) - 120, 120):
                        seg = sorted(x for x in (b.get("v") or 0 for b in bars[s0:s0 + 120]) if x > 0)
                        if seg and med > 0 and seg[len(seg) // 2] < med * 0.01:
                            seg_bad += 1
                    if seg_bad:
                        vol_bad.append("%s 有 %d 段成交量塌陷（基准中位 %.0f）" % (p, seg_bad, med))
        except Exception as exc:                        # noqa: BLE001
            short.append("%s ERR %s" % (p, exc))
    check("加权日K 覆盖全量历史（≥%d 根）" % MIN_BARS, not short,
          ("; ".join(short[:6]) if short else "全部达标"))
    check("加权日K 历史段成交量量级合理（未漏当月合约）", not vol_bad,
          ("; ".join(vol_bad[:6]) if vol_bad else "全部合理"))

    print("\n========== 8. 加权K线周期适配 ==========")
    for p, per in [("SA", "1"), ("SA", "5"), ("SA", "60")]:
        try:
            k = api("/api/kline", symbol=p + "W", period=per)["data"]
            check("加权 %s 分钟线可用（period=%s）" % (p, per), len(k["bars"]) > 0,
                  "%d 根" % len(k["bars"]))
        except Exception as exc:                        # noqa: BLE001
            check("加权 %s 分钟线可用（period=%s）" % (p, per), False, str(exc))

    print("\n" + "=" * 72)
    print("  总计 %d 项，通过 %d 项，失败 %d 项" % (ok + fail, ok, fail))
    if fails:
        print("  失败：" + " | ".join(fails[:10]))
    print("=" * 72)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
