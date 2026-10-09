# -*- coding: utf-8 -*-
"""
广期所 / 全品种「加权指数」与「主连」行情
============================================

背景
----
新浪财经只提供**主力连续合约**（XX0，即持仓量最大那一个月份的行情），
并没有真正的「加权指数」。而加权指数必须由该品种**所有在交易合约**
按权重合成，新浪的 `XX99` / `XX888` 这类代码实测全部为空。

本模块做两件事：
  1. **本地合成加权指数**（默认，零依赖）
     用新浪已经拿到的全部月份合约快照，按持仓量（或成交量）加权
     计算最新价 / 涨跌 / 开高低收，权重口径与文华、博易的
     「商品指数」一致。
  2. **天勤（快期）官方指数对接**（可选，需 auth）
     若配置了 tianqin.json，则用 tqsdk 的 KQ.i@<EXCH>.<prod>（指数）
     与 KQ.m@<EXCH>.<prod>（主连）拿官方数据，作为校准与对照。

加权算法
--------
    最新价 = Σ(price_i × w_i) / Σ(w_i)
    权重 w_i = 该合约**昨结算时的持仓量**（保证全天权重稳定，不随
              日内持仓变化导致指数抖动）；缺失时退化为当前持仓量。

    涨跌基准：用同一权重对「昨结算价」加权 —— 这样
        Σ(w_i × (last_i - presettle_i)) / Σw
    就是指数相对昨日结算的变动，口径与单个合约完全一致。

合成 K 线（日/分钟）
--------------------
    开 = Σ(o_i·w_i)/Σw   高 = Σ(h_i·w_i)/Σw
    低 = Σ(l_i·w_i)/Σw   收 = Σ(c_i·w_i)/Σw
    量 = Σv_i           持仓 = Σoi_i
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime

# --------------------------------------------------------------------------- #
# 天勤配置文件定位（源码运行 vs PyInstaller 打包运行）
#
# 查找顺序（先命中先用）：
#   1) 环境变量 TIANQIN_CONFIG 指定的路径
#   2) exe / 脚本**同目录**的 tianqin.json —— 用户可改、可覆盖内置账号
#      打包后这一份是"外置"文件，方便换账号而不必重新打包
#   3) 打包内置资源目录（_MEIPASS）里的 tianqin.json —— 出厂默认账号
# --------------------------------------------------------------------------- #
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    _BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    _EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = _BUNDLE_DIR

BASE_DIR = _BUNDLE_DIR

# 内置（打包进 exe）的那一份
TQ_CONFIG_EMBEDDED = os.path.join(_BUNDLE_DIR, "tianqin.json")
# 外置（放在 exe 旁边）的那一份，优先级更高
TQ_CONFIG_EXTERNAL = os.path.join(_EXE_DIR, "tianqin.json")


def _resolve_tq_config_path() -> str:
    """按优先级挑出实际使用的 tianqin.json 路径。"""
    env = os.environ.get("TIANQIN_CONFIG", "").strip()
    if env and os.path.isfile(env):
        return env
    # 外置优先：即使内置有账号，也允许用户用外置文件覆盖或停用
    if os.path.isfile(TQ_CONFIG_EXTERNAL):
        return TQ_CONFIG_EXTERNAL
    return TQ_CONFIG_EMBEDDED


TQ_CONFIG_PATH = _resolve_tq_config_path()

# --------------------------------------------------------------------------- #
# 数据源选择标记
# --------------------------------------------------------------------------- #
SOURCE_LOCAL = "local"        # 本地按持仓量加权合成
SOURCE_TIANQIN = "tianqin"    # 天勤官方指数 / 主连

# 合成指数时，某一时刻"有真实行情"的合约权重占**全体成分权重**的比例低于该阈值，
# 就不出该时刻的 K 线。
#
# 为什么分母是全体权重而不是"当刻可用权重"：
# 成分权重取自**当前**持仓量（固定值）。若某合约当时尚未上市/开盘，按"仅对可用
# 权重归一"会让少数合约单独决定指数，得到与真实指数相差巨大的脏值（实测早期
# 加权日K 算出 1371，而当前真实指数约 1010）。因此要求"真实可用的权重"必须覆盖
# 全体成分权重的绝大部分，早期数据不足的时段直接不出 K 线。
MIN_REAL_COVER = 0.9


# --------------------------------------------------------------------------- #
# 一、本地加权合成
# --------------------------------------------------------------------------- #

def _weight_of(item: dict, mode: str) -> float:
    """单个合约的权重。

    mode="oi"   → 持仓量加权（默认，指数连续性好）
    mode="vol"  → 成交量加权

    优先用「昨持仓量」这类不随日内变动而变的量；这里退化为当前值，
    因为在同一批快照内所有合约取的是同一时刻，比值是稳定的。
    """
    if mode == "vol":
        return float(item.get("volume") or 0.0)
    return float(item.get("oi") or 0.0)


def build_weighted_index(items: list[dict], mode: str = "oi") -> dict | None:
    """把某品种全部在交易合约合成为一条加权指数行情。

    items: /api/symbols 里那种结构，需含 code/last/presettle/open/high/low/
           volume/oi。主力连续（XX0）必须排除——它不是真实月份合约，
           纳入会把主力所在月份的权重算两遍。

    返回与单合约行情同构的 dict（code=XXW），供前端直接复用渲染逻辑；
    数据不足（有效合约 < 2）时返回 None。
    """
    rows = []
    for it in items:
        code = str(it.get("code") or "")
        if not code or re.fullmatch(r"[A-Za-z]{1,2}0", code):
            continue                                    # 跳过主力连续
        w = _weight_of(it, mode)
        last = float(it.get("last") or 0.0)
        if w <= 0 or last <= 0:
            continue                                    # 权重/价格无效
        rows.append({
            "code": code,
            "w": w,
            "last": last,
            "presettle": float(it.get("presettle") or 0.0) or last,
            "open": float(it.get("open") or 0.0) or last,
            "high": float(it.get("high") or 0.0) or last,
            "low": float(it.get("low") or 0.0) or last,
            "volume": float(it.get("volume") or 0.0),
            "oi": float(it.get("oi") or 0.0),
        })

    if len(rows) < 2:
        return None

    # 只取权重前 N 大（剔除权重几乎为 0 的僵尸合约），并归一到 100%
    rows.sort(key=lambda r: -r["w"])
    total_all = sum(r["w"] for r in rows) or 1.0
    keep, acc = [], 0.0
    for r in rows:
        keep.append(r)
        acc += r["w"]
        if acc / total_all >= 0.999:                    # 已覆盖 99.9%
            break
    wsum = sum(r["w"] for r in keep) or 1.0

    def wavg(key: str) -> float:
        return sum(r[key] * r["w"] for r in keep) / wsum

    last = wavg("last")
    presettle = wavg("presettle")
    change = last - presettle
    pct = (change / presettle * 100.0) if presettle else 0.0

    # 各合约涨跌幅也加权，用于「加权涨跌幅」的另一种口径交叉校验
    return {
        "code": None,                                   # 由调用方填 product + "W"
        "name": "",
        "product": "",
        "isMain": False,
        "isWeighted": True,
        "weightMode": mode,
        "time": "",
        "date": "",
        "open": round(wavg("open"), 4),
        "high": round(wavg("high"), 4),
        "low": round(wavg("low"), 4),
        "last": round(last, 4),
        "bid": 0.0,
        "ask": 0.0,
        "settle": 0.0,
        "presettle": round(presettle, 4),
        "bidvol": 0,
        "askvol": 0,
        "oi": int(sum(r["oi"] for r in keep)),
        "volume": int(sum(r["volume"] for r in keep)),
        "exchange": "",
        "change": round(change, 4),
        "pct": round(pct, 6),
        "members": len(keep),
        "components": [
            {"code": r["code"], "weight": round(r["w"] / wsum, 6),
             "last": r["last"]}
            for r in keep
        ],
    }


def synth_index_timeshare(symbol_sets: list[list[dict]],
                         mode: str = "oi") -> list[dict]:
    """把多合约的分时序列按时间戳对齐后加权，得到指数分时。

    symbol_sets: [[该合约的 timeshare points, 及其权重], ...]
                 每个 points 元素形如 {t, c, avg, v, oi}
    返回形如单合约分时的 points 列表。

    时间轴以**所有合约时间戳的并集**为准：某合约在某分钟没有数据
    （如冷门合约成交稀疏）时，用该合约的**前一个有效价**填充，
    再参与加权 —— 这样指数不会因某个合约缺一分钟而断点。
    """
    if not symbol_sets:
        return []
    stamps: list[str] = []
    seen = set()
    for series in symbol_sets:
        for p in series:
            t = p.get("t")
            if t and t not in seen:
                seen.add(t)
                stamps.append(t)
    stamps.sort()

    # 每条序列做「向前填充」，得到按 stamps 对齐的价格/成交量/持仓
    filled = []
    for series in symbol_sets:
        m = {p["t"]: p for p in series if p.get("t")}
        rows, last_c, last_avg, cum_v, cum_oi = [], None, None, 0.0, 0.0
        for t in stamps:
            p = m.get(t)
            if p:
                last_c = p.get("c", last_c)
                last_avg = p.get("avg", last_avg)
                cum_v = p.get("v", cum_v)                # 分时里的 v 是累计量
                cum_oi = p.get("oi", cum_oi)
            rows.append({"c": last_c, "avg": last_avg, "v": cum_v, "oi": cum_oi})
        filled.append(rows)

    out = []
    for i, t in enumerate(stamps):
        num = den = 0.0
        nums_avg = dens_avg = 0.0
        tot_v = tot_oi = 0.0
        for k, rows in enumerate(filled):
            w = _series_weight(symbol_sets, k, mode, rows[i])
            if w <= 0:
                continue
            c = rows[i]["c"]
            if c is None or c <= 0:
                continue
            num += c * w
            den += w
            a = rows[i]["avg"]
            if a and a > 0:
                nums_avg += a * w
                dens_avg += w
            tot_v += rows[i]["v"] or 0.0
            tot_oi += rows[i]["oi"] or 0.0
        if den <= 0:
            continue
        out.append({
            "t": t,
            "c": round(num / den, 4),
            "avg": round(nums_avg / dens_avg, 4) if dens_avg > 0 else round(num / den, 4),
            "v": tot_v / len(symbol_sets),
            "oi": tot_oi,
        })
    return out


def _series_weight(sets: list, k: int, mode: str, row: dict) -> float:
    """分时加权时，用该合约当日累计持仓/成交量作为权重（随时间演进）。"""
    if mode == "vol":
        return float(row.get("v") or 0.0)
    return float(row.get("oi") or 0.0)


def synth_index_timeshare_weighted(series_list: list[list[dict]],
                                  weights: list[float]) -> list[dict]:
    """对多条分时序列按固定权重加权（权重由调用方按持仓量算好）。

    与 synth_index_timeshare 的区别：这里权重是**外部传入的固定值**
    （整日的持仓量），而不是随分时点变化 —— 保证同一天的指数权重稳定。

    series_list[i] 为第 i 个合约的 points（元素 {t,c,avg,v,oi}），
    weights[i] 为其权重。时间轴取所有序列时间戳的并集，
    缺数据的时刻用该序列前一个有效价向前填充。
    """
    if not series_list or not weights:
        return []
    stamps, seen = [], set()
    for series in series_list:
        for p in series:
            t = p.get("t")
            if t and t not in seen:
                seen.add(t)
                stamps.append(t)
    stamps.sort()

    filled = []
    for series in series_list:
        m = {p["t"]: p for p in series if p.get("t")}
        rows, last_c, last_avg, cum_v, cum_oi = [], None, None, 0.0, 0.0
        for t in stamps:
            p = m.get(t)
            if p:
                last_c = p.get("c", last_c)
                last_avg = p.get("avg", last_avg)
                cum_v = p.get("v", cum_v)
                cum_oi = p.get("oi", cum_oi)
            rows.append({"c": last_c, "avg": last_avg, "v": cum_v, "oi": cum_oi})
        filled.append(rows)

    out = []
    for i, t in enumerate(stamps):
        num = den = n_avg = d_avg = 0.0
        tot_v = tot_oi = 0.0
        for k, rows in enumerate(filled):
            w = float(weights[k]) if k < len(weights) else 0.0
            c = rows[i]["c"]
            if w <= 0 or c is None or c <= 0:
                continue
            num += c * w
            den += w
            a = rows[i]["avg"]
            if a and a > 0:
                n_avg += a * w
                d_avg += w
            tot_v += rows[i]["v"] or 0.0
            tot_oi += rows[i]["oi"] or 0.0
        if den <= 0:
            continue
        out.append({
            "t": t,
            "c": round(num / den, 4),
            "avg": round(n_avg / d_avg, 4) if d_avg > 0 else round(num / den, 4),
            "v": tot_v,
            "oi": tot_oi,
        })
    return out


def synth_index_kline(series_list: list[list[dict]],
                      weights: list[float] | None = None,
                      mode: str = "oi") -> list[dict]:
    """对多条 K 线序列按时间戳对齐后加权，合成指数 K 线。

    权重取值有两种模式，**历史 K 线必须用逐bar动态权重**：

    * ``mode="auto"``（推荐，历史 K 线用）：权重 = **该根 K 线自身的持仓量
      （或成交量）**，逐 bar 变化。这是唯一正确的历史口径 —— 因为各合约的
      主力月份会随时间轮换，用"今天的持仓量"当历史权重会把早已退市的当月
      合约（如 2026-03 的 SA2605 成交 115 万手）完全漏掉，只留下当时几乎
      不成交的远月（实测成交量被低估 200 倍）。
    * ``mode="fixed"``：权重 = 外部传入的 ``weights``（当刻快照），用于
      日内分时（同一交易日内权重稳定）。

    bars 元素形如 {t,o,h,l,c,v,oi}。时间轴取并集，缺失时刻向前填充收盘价
    （开高低都用该填充价，保证不引入虚假波动）。成交量/持仓量求和。
    """
    if not series_list:
        return []
    fixed = (mode == "fixed")
    if fixed and not weights:
        return []

    stamps, seen = [], set()
    for bars in series_list:
        for b in bars:
            t = b.get("t")
            if t and t not in seen:
                seen.add(t)
                stamps.append(t)
    stamps.sort()

    filled = []
    real = []                                   # real[k][i] = 该时刻是否为本合约真实成交K
    for bars in series_list:
        m = {b["t"]: b for b in bars if b.get("t")}
        rows, flags, last_c = [], [], None
        for t in stamps:
            b = m.get(t)
            if b:
                last_c = b.get("c", last_c)
                rows.append(dict(b))
                flags.append(True)
            else:
                # 缺失时刻用前收盘价填充（开高低都用填充价，不制造虚假波动）。
                # 注意：在首根真实K之前没有可填充值 → c 置 None，标记为非真实，
                # 该时刻不计入加权（否则会把"某合约还没上市"误当成"价格为0/前值"）。
                c = last_c
                rows.append({"t": t, "o": c, "h": c, "l": c, "c": c,
                             "v": 0.0, "oi": 0.0})
                flags.append(False)
        filled.append(rows)
        real.append(flags)

    out = []
    for i, t in enumerate(stamps):
        wsum = 0.0
        real_w = 0.0                            # 该时刻"有真实行情"的合约权重合计
        o = h = l = c = 0.0
        tot_v = tot_oi = 0.0
        for k, rows in enumerate(filled):
            if not real[k][i]:
                continue                        # 只用当刻真实成交的合约定权与定价
            b = rows[i]
            if b.get("c") is None:
                continue
            if fixed:
                w = float(weights[k]) if k < len(weights) else 0.0
            else:
                # 动态权重：该根 K 线自身的持仓量（oi 缺失时退化为成交量）
                w = float(b.get("oi") or 0.0)
                if w <= 0:
                    w = float(b.get("v") or 0.0)
            if w <= 0:
                continue
            o += (b.get("o") or b["c"]) * w
            h += (b.get("h") or b["c"]) * w
            l += (b.get("l") or b["c"]) * w
            c += b["c"] * w
            wsum += w
            real_w += w
            tot_v += b.get("v") or 0.0
            tot_oi += b.get("oi") or 0.0
        if wsum <= 0:
            continue
        # 覆盖度护栏：参与定价的合约数量太少（<2 个）时不足以代表指数。
        # 动态模式下权重分母就是当刻可用权重，故只检查"至少两个真实合约"。
        if not fixed and sum(1 for k in range(len(filled)) if real[k][i]) < 2:
            continue
        # 固定权重模式（分时快照）：要求真实权重覆盖全体成分的绝大部分
        if fixed:
            total_w = sum(float(w) for w in weights if w and w > 0) or 1.0
            if real_w / total_w < MIN_REAL_COVER:
                continue
        out.append({
            "t": t,
            "o": round(o / wsum, 4),
            "h": round(h / wsum, 4),
            "l": round(l / wsum, 4),
            "c": round(c / wsum, 4),
            "v": tot_v,
            "oi": tot_oi,
        })
    return out


# --------------------------------------------------------------------------- #
# 二、天勤（快期）官方主连 / 指数
# --------------------------------------------------------------------------- #

TQ_EXCHANGE_MAP = {
    "郑商所": "CZCE",
    "大商所": "DCE",
    "上期所": "SHFE",
    "中金所": "CFFEX",
    "广期所": "GFEX",
    "能源中心": "INE",
}

# 天勤合约代码大小写：郑商所/中金所用大写，上期所/大商所/广期所/能源中心用小写
# （实测 KQ.i@SHFE.rb 正常、KQ.i@SHFE.RB 报 non-existent instrument）
TQ_LOWER_EXCH = frozenset({"SHFE", "DCE", "GFEX", "INE"})


def tq_symbol(exch: str, product: str, kind: str = "i") -> str:
    """拼天勤连续合约代码：kind='i' 指数 / 'm' 主连。"""
    p = product.upper()
    if exch in TQ_LOWER_EXCH:
        p = p.lower()
    return "KQ.%s@%s.%s" % (kind, exch, p)

_tq_lock = threading.Lock()
_tq_api = None
_tq_quotes: dict[str, dict] = {}
_tq_cache_at = 0.0
TQ_CACHE_TTL = 3.0
_TQ_LAST_ERROR = ""


def load_tq_config() -> dict:
    """读 tianqin.json；不存在或未启用则返回 {'enabled': False}。

    每次都重新解析路径：这样用户把外置 tianqin.json 放到 exe 旁边之后，
    下次查询即生效，不必重启。
    """
    global TQ_CONFIG_PATH
    path = _resolve_tq_config_path()
    if path != TQ_CONFIG_PATH:
        TQ_CONFIG_PATH = path
        _TQ_LAST_ERROR = ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:                                   # noqa: BLE001
        return {"enabled": False}
    user = str(cfg.get("auth_user") or "").strip()
    pwd = str(cfg.get("auth_pass") or "").strip()
    enabled = bool(cfg.get("enabled")) and bool(user) and bool(pwd)
    return {"enabled": enabled, "auth_user": user, "auth_pass": pwd,
            "config_path": path}


def tq_status() -> dict:
    cfg = load_tq_config()
    ok = False
    ver = ""
    import_err = ""
    try:
        import tqsdk                                 # noqa: F401
        ver = getattr(tqsdk, "__version__", "")
        ok = True
    except Exception as exc:                         # noqa: BLE001
        import_err = "%s: %s" % (type(exc).__name__, exc)
    return {
        "installed": ok,
        "version": ver,
        "importError": import_err,
        "configured": cfg["enabled"],
        "connected": _tq_api is not None,
        "lastError": _TQ_LAST_ERROR,
        "configPath": cfg.get("config_path", ""),
        "configExternal": os.path.isfile(TQ_CONFIG_EXTERNAL),
    }


def _tq_ensure_api():
    """惰性创建 TqApi 连接（单例，进程内复用）。"""
    global _tq_api, _TQ_LAST_ERROR
    if _tq_api is not None:
        return _tq_api
    cfg = load_tq_config()
    if not cfg["enabled"]:
        _TQ_LAST_ERROR = "未配置快期账号（tianqin.json）"
        return None
    try:
        import tqsdk
        # 3.10+ 必须是 TqAuth 对象；传 tuple / 裸字符串都不生效（会报"请输入 auth"）
        auth = tqsdk.TqAuth(cfg["auth_user"], cfg["auth_pass"])
        # web_gui=False 不启本地面板；disable_print=True 抑制免责/账户等刷屏日志
        try:
            _tq_api = tqsdk.TqApi(auth=auth, web_gui=False, disable_print=True)
        except TypeError:                               # 老版本不认某些参数
            _tq_api = tqsdk.TqApi(auth=auth)
        # 预热：TqApi 构造后数据通道尚未完全就绪，直接查 KQ.m/KQ.i 会偶发超时。
        # 先订阅一个必然存在的合约并等一次更新，把通道带起来。
        try:
            _tq_api.get_quote("SHFE.rb2601")
        except Exception:                               # noqa: BLE001
            pass
        _TQ_LAST_ERROR = ""
        return _tq_api
    except Exception as exc:                            # noqa: BLE001
        _TQ_LAST_ERROR = "%s: %s" % (type(exc).__name__, exc)
        _tq_api = None
        return None


def tq_quote_set(product: str, exchange_cn: str) -> dict | None:
    """取天勤的 KQ.m（主连）与 KQ.i（指数）快照。

    返回 {'main': {...}, 'index': {...}}，取不到返回 None。
    任何失败都会记录到 _TQ_LAST_ERROR，便于 /api/tq/status 排查。
    """
    global _tq_quotes, _tq_cache_at, _TQ_LAST_ERROR
    exch = TQ_EXCHANGE_MAP.get(exchange_cn)
    if not exch:
        _TQ_LAST_ERROR = "未知交易所：%s" % exchange_cn
        return None
    conn_key = "%s.%s" % (exch, product.upper())        # 缓存键统一大写
    now = time.time()
    with _tq_lock:
        if _tq_quotes.get(conn_key) and now - _tq_cache_at < TQ_CACHE_TTL:
            return _tq_quotes[conn_key]
        api = _tq_ensure_api()
        if api is None:
            return None
        try:
            syms = [tq_symbol(exch, product, "m"), tq_symbol(exch, product, "i")]
            qs = api.get_quote_list(syms)
            res = {}
            for s, tag in zip(qs, ("main", "index")):
                # 注意：KQ.m 返回 Quote 对象、KQ.i 返回 D 实体，字段访问方式不同。
                # Quote 支持 q["x"]（内部转发到 _data），D 本身就是 dict 子类，
                # 所以统一用 [] 取值最稳（getattr 在 D 上取不到字段）。
                def g(name, default=None):
                    try:
                        v = s[name]
                    except Exception:               # noqa: BLE001
                        return default
                    return default if v is None else v

                last = g("last_price")
                if last is None or (isinstance(last, float) and last != last):
                    continue                         # 无价（未上市/停牌/nan）

                def fnum(name, default=0.0):
                    """天勤在非交易时段常把 bid/ask 等返回为 nan。
                    nan 经 json.dumps 会写成裸 NaN（非法 JSON），前端 res.json() 直接抛错，
                    因此在源头统一收敛为 default。"""
                    v = g(name, default)
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        return default
                    return default if (v != v or v in (float("inf"), float("-inf"))) else v

                def inum(name, default=0):
                    v = g(name, default)
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        return default
                    return default if (v != v or v in (float("inf"), float("-inf"))) else int(v)

                res[tag] = {
                    "source": SOURCE_TIANQIN,
                    "symbol": g("instrument_id", ""),
                    "name": g("instrument_name", ""),
                    "underlying": g("underlying_symbol", ""),
                    "datetime": g("datetime", ""),
                    "last": fnum("last_price"),
                    "open": fnum("open"),
                    "high": fnum("highest"),
                    "low": fnum("lowest"),
                    "presettle": fnum("pre_settlement"),
                    "preclose": fnum("pre_close"),
                    "volume": inum("volume"),
                    "oi": inum("open_interest"),
                    "bid": fnum("bid_price1"),
                    "ask": fnum("ask_price1"),
                }
            if not res:
                _TQ_LAST_ERROR = "天勤返回空行情（%s 可能无 KQ.i/KQ.m 合约）" % conn_key
                return None
            _tq_quotes[conn_key] = res
            _tq_cache_at = now
            _TQ_LAST_ERROR = ""
            return res
        except Exception as exc:                        # noqa: BLE001
            _TQ_LAST_ERROR = "%s: %s" % (type(exc).__name__, exc)
            return None
