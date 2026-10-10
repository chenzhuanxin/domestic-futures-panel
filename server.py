# -*- coding: utf-8 -*-
"""
纯碱（SA）期货行情面板 · Python 后端服务
==========================================

数据源：新浪财经期货公开接口（免费，无需登录、无需 Key）
    · 实时行情   https://hq.sinajs.cn/list=nf_<CODE>
    · 分时走势   .../InnerFuturesNewService.getMinLine?symbol=<CODE>
    · 分钟 K 线  .../InnerFuturesNewService.getFewMinLine?symbol=<CODE>&type=<N>
    · 日 K 线    .../InnerFuturesNewService.getDailyKLine?symbol=<CODE>

对外 HTTP 接口（供前端 index.html 调用）：
    GET /                          前端面板页面
    GET /api/quote?symbol=SA2701   实时行情
    GET /api/symbols?product=SA    同品种全部挂牌合约快照（含主力标记）
    GET /api/timeshare?symbol=..   当日分时（价 / 均价 / 量 / 持仓）
    GET /api/kline?symbol=..&period=1|5|15|30|60|120|day   K 线

特点：
    · 纯标准库实现，零第三方依赖（不需要 pip install）
    · 绕过本机 HTTP 代理直连，避免代理端口漂移导致 502
    · 内存 TTL 缓存 + 上游异常时回退上次成功数据
    · 自动寻找可用端口并打开浏览器

用法：
    python server.py                     # 默认 SA2701，端口 8686
    python server.py --port 9000         # 指定端口
    python server.py --symbol SA2705     # 指定合约
    python server.py --no-browser        # 不自动打开浏览器
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import weighted_index as WINDEX

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 路径（源码运行 vs PyInstaller 打包运行）
#
# PyInstaller 单文件模式会把所有资源解压到一个临时目录，`__file__` 指向那里，
# 而 `sys._MEIPASS` 才是资源根。若源码里继续用 `dirname(__file__)` 找 index.html，
# 打包后就会 404。因此这里区分两类目录：
#   · BUNDLE_DIR —— 只读资源（index.html 等），打包后就位于 _MEIPASS 内
#   · EXE_DIR    —— exe 实际所在目录，用于存放**用户可改**的配置和缓存
# --------------------------------------------------------------------------- #
IS_FROZEN = bool(getattr(sys, "frozen", False))

# 只读资源根目录
if IS_FROZEN:
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

# 可写/可改目录（exe 或脚本所在目录）
EXE_DIR = (os.path.dirname(os.path.abspath(sys.executable))
           if IS_FROZEN else BUNDLE_DIR)

# 兼容旧代码：静态资源继续走 APP_DIR
APP_DIR = BUNDLE_DIR

# 面板前端 HTML 的文件名。
#   · 本地开发 / PyInstaller 打包  —— 叫 index.html
#   · GitHub 仓库                 —— 叫 app.html（根目录 index.html 让给 Pages 落地页）
# 两个名字都认，谁先存在用谁，这样"克隆仓库直接跑"和"运行 exe"都能开箱可用。
PANEL_HTML_NAMES = ("index.html", "app.html")
_PANEL_HTML_CACHE = None


def panel_html_path() -> str:
    """定位面板前端 HTML（带缓存）。找不到时返回 index.html 的路径，交由 _static 报 404。"""
    global _PANEL_HTML_CACHE
    if _PANEL_HTML_CACHE and os.path.isfile(_PANEL_HTML_CACHE):
        return _PANEL_HTML_CACHE
    for name in PANEL_HTML_NAMES:
        cand = os.path.join(APP_DIR, name)
        if os.path.isfile(cand):
            _PANEL_HTML_CACHE = cand
            return cand
    return os.path.join(APP_DIR, PANEL_HTML_NAMES[0])


DEFAULT_SYMBOL = "SA2701"
DEFAULT_PRODUCT = "SA"
DEFAULT_PORT = 8686

SINA_HQ_API = "https://hq.sinajs.cn/list="
SINA_FUT_API = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
                "var%20t=/InnerFuturesNewService.")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SINA_REFERER = "https://finance.sina.com.cn"

# 合约代码合法性（如 SA2701 / RB2610 / IF2603），以及主力连续 XX0
SYMBOL_RE = re.compile(r"^[A-Za-z]{1,2}\d{3,4}$")
MAIN_SYMBOL_RE = re.compile(r"^[A-Za-z]{1,2}0$")
WEIGHTED_SYMBOL_RE = re.compile(r"^[A-Za-z]{1,2}W$")     # 加权指数（本地合成）
PRODUCT_RE = re.compile(r"^[A-Za-z]{1,2}$")
# 主力/指数合约：品种代码 + 0（如 RB0 = 螺纹钢主力连续）
MAIN_CODE_RE = re.compile(r"^([A-Za-z]{1,2})0$")

EXCHANGE_CN = {
    "郑": "郑商所", "郑商所": "郑商所", "CZCE": "郑商所",
    "上": "上期所", "上海期货交易所": "上期所", "SHFE": "上期所",
    "连": "大商所", "大连商品交易所": "大商所", "DCE": "大商所",
    "能源": "上期能源", "INE": "上期能源",
    "中金": "中金所", "CFFEX": "中金所",
    "广": "广期所", "GFEX": "广期所",
}

# --------------------------------------------------------------------------- #
# 全品种字典
# --------------------------------------------------------------------------- #
# 品种中文名以"新浪主力连续合约(nf_XX0)的实时名称"为权威来源，这里只维护
# 交易所归属（行情里不返回交易所字段），中文名缺失时由程序自动补齐。
# 数据来源：新浪 finance.sina.com.cn/futures/quotes/iframe/js/futures_symbol_js.js
#          的 jys_data.pz（官方品种表）+ 实盘补充品种（纯碱/碳酸锂等新浪表未收录）。
EXCHANGE_PRODUCTS: dict[str, tuple[str, ...]] = {
    "郑商所": (
        "AP", "CF", "CJ", "CY", "FG", "JR", "LR", "MA", "OI", "PF", "PK",
        "PM", "PR", "PX", "RI", "RM", "RS", "SA", "SF", "SH", "SM", "SR",
        "TA", "UR", "WH", "ZC",
    ),
    "大商所": (
        "A", "B", "BB", "C", "CS", "EG", "FB", "I", "J", "JD", "JM", "L",
        "LG", "LH", "M", "P", "PG", "PP", "V", "Y",
    ),
    "上期所": (
        "AG", "AL", "AO", "AU", "BC", "BR", "BU", "CU", "FU", "HC", "LU",
        "NI", "NR", "PB", "RB", "RU", "SC", "SN", "SP", "SS", "WR", "ZN",
    ),
    "中金所": (
        "IC", "IF", "IH", "IM", "T", "TF", "TL", "TS",
    ),
    "广期所": (
        "LC", "PS", "SI",
    ),
}

# 新浪行情不返回交易所字段，用品种代码反查
PRODUCT_EXCHANGE: dict[str, str] = {
    p: ex for ex, plist in EXCHANGE_PRODUCTS.items() for p in plist
}

# 中金所行情不返回中文名，而这几个品种代码靠猜没意义 —— 只给中金所补名称表
CFFEX_NAMES = {
    "IC": "中证500", "IF": "沪深300", "IH": "上证50", "IM": "中证1000",
    "T": "10年国债", "TF": "5年国债", "TL": "30年国债", "TS": "2年国债",
}

# 品种 → 合约代码清单（启动时由 fetch_all_products 填充并缓存）
PRODUCT_TABLE: dict[str, dict] = {}
PRODUCT_TABLE_LOCK = threading.Lock()
PRODUCT_TABLE_AT = 0.0
PRODUCT_TABLE_TTL = 1800.0        # 品种树半小时刷新一次

# 中金所品种的行情字段布局与商品期货不同（见 parse_quote_line）
CFFEX_PRODUCTS = frozenset(EXCHANGE_PRODUCTS["中金所"])

# 分钟 K 线上限：新浪 getFewMinLine 单次最多返回约 1023 根
MINUTE_KLINE_LIMIT = 1023

# --------------------------------------------------------------------------- #
# HTTP 抓取
# --------------------------------------------------------------------------- #

# 关键：显式禁用系统代理。本机系统代理端口会漂移，走代理时经常 502。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _decode(raw: bytes) -> str:
    """新浪接口多为 GBK 编码，逐个尝试。"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def http_get(url: str, referer: str | None = None, timeout: int = 10,
             retries: int = 2) -> str:
    """带重试的 GET。失败抛出最后一次异常。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            req.add_header("Accept", "*/*")
            req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
            if referer:
                req.add_header("Referer", referer)
            with _OPENER.open(req, timeout=timeout) as resp:
                return _decode(resp.read())
        except Exception as exc:                      # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(0.35 * (attempt + 1))
    raise last_err if last_err else RuntimeError("http_get failed")


def parse_jsonp(text: str):
    """从 `var t=([...]);` 中抠出 JSON 数组。

    上游对无数据合约会返回 `var t=(null);` —— 归一化成空列表，
    避免调用方拿到 None 后抛 TypeError。
    """
    m = re.search(r"=\s*\((.*)\)\s*;?\s*$", text.strip(), re.S)
    if not m:
        return []
    body = m.group(1).strip()
    if not body or body.lower() == "null":
        return []
    try:
        out = json.loads(body)
    except ValueError:
        return []
    return out if isinstance(out, list) else []


def num(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def numi(value, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# TTL 缓存
# --------------------------------------------------------------------------- #

class TTLCache:
    """带过期时间的线程安全缓存；上游报错时回退上一次成功数据。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get_or(self, key: str, ttl: float, producer):
        now = time.time()
        with self._lock:
            item = self._data.get(key)
        if item and now - item[0] < ttl:
            return item[1]
        try:
            value = producer()
        except Exception:
            if item:                      # 上游挂了 → 退回旧数据，保证面板不白屏
                return item[1]
            raise
        with self._lock:
            self._data[key] = (time.time(), value)
        return value

    def age(self, key: str) -> float | None:
        with self._lock:
            item = self._data.get(key)
        return None if not item else time.time() - item[0]


CACHE = TTLCache()


# --------------------------------------------------------------------------- #
# 交易时段判断（用于动态调整缓存时间）
# --------------------------------------------------------------------------- #

def is_trading_now() -> bool:
    """郑商所纯碱交易时段：夜盘 21:00-23:00，日盘 9:00-11:30 / 13:30-15:00。"""
    now = datetime.now()
    if now.weekday() >= 5:                       # 周六、周日休市
        return False
    hm = now.hour * 60 + now.minute
    return (21 * 60 <= hm <= 23 * 60
            or 9 * 60 <= hm <= 10 * 60 + 15
            or 10 * 60 + 30 <= hm <= 11 * 60 + 30
            or 13 * 60 + 30 <= hm <= 15 * 60)


def tick_ttl(fast: float, slow: float) -> float:
    return fast if is_trading_now() else slow


# --------------------------------------------------------------------------- #
# 数据抓取与解析
# --------------------------------------------------------------------------- #

def parse_quote_line(line: str):
    """解析一行 `var hq_str_nf_SA2701="...";`

    新浪期货行情有两种字段布局：
      · 商品期货（郑商所/大商所/上期所/广期所）44 字段，f[0]=名称
      · 中金所（股指 / 国债）50 字段，f[0] 直接是价格，没有名称字段
    这里统一归一化成同一种结构，并补上产品代码与交易所。
    """
    m = re.match(r'var\s+hq_str_nf_(\w+)\s*=\s*"(.*)"\s*;', line.strip())
    if not m:
        return None
    code, body = m.group(1), m.group(2)
    if not body:
        return None
    f = body.split(",")
    if len(f) < 18:
        return None

    cm = re.fullmatch(r"([A-Za-z]{1,2})(\d{3,4}|0)", code)
    product = cm.group(1).upper() if cm else ""
    is_cffex = len(f) >= 44 and product in CFFEX_PRODUCTS
    is_main = bool(code.upper().endswith("0") and cm)

    if is_cffex:
        # 中金所 50 字段布局（实测校准）：
        #   f[0]=开 f[1]=高 f[2]=低 f[3]=最新 f[4]=成交量 f[5]=成交额
        #   f[6]=持仓 f[9]=结算(盘中常无效) f[10]=昨结算 f[11]/f[12]=买量/卖量
        #   f[13]/f[14]=买价/卖价（可能出现交叉等无效值，需校验）
        last = num(f[3]) or num(f[0])
        name = ""
        open_p, high, low = num(f[0]), num(f[1]), num(f[2])
        volume, oi = numi(f[4]), numi(f[6])
        bid, ask = num(f[13]), num(f[14])
        if not (bid > 0 and ask > 0 and bid <= ask * 1.001):  # 无效买卖盘
            bid = ask = 0.0
        bidvol, askvol = numi(f[11]), numi(f[12])
        exchange = "中金所"
    else:
        name = f[0].strip()
        last = num(f[8])
        open_p, high, low = num(f[2]), num(f[3]), num(f[4])
        bid, ask = num(f[6]), num(f[7])
        oi, volume = numi(f[13]), numi(f[14])
        exchange = EXCHANGE_CN.get(f[15].strip(), f[15].strip())

    presettle = num(f[10]) or num(f[9])          # 昨结算（涨跌基准）
    if presettle <= 0:
        presettle = num(f[5]) or last
    change = last - presettle
    pct = (change / presettle * 100.0) if presettle else 0.0

    return {
        "code": code,
        "name": name,
        "product": product,
        "isMain": is_main,
        "time": f[1].strip() if not is_cffex else "",
        "date": f[17].strip(),
        "open": open_p,
        "high": high,
        "low": low,
        "last": last,
        "bid": bid,
        "ask": ask,
        "settle": (lambda s: s if low <= s <= high else 0.0)(num(f[9]) or 0.0),
        # 今结算（中金所 f[9] 盘中可能给无效值，落在高低价区间外则置 0；商品正常）
        "presettle": presettle,                  # 昨结算
        "bidvol": numi(f[11]) if not is_cffex else 0,
        "askvol": numi(f[12]) if not is_cffex else 0,
        "oi": oi,                                # 持仓量
        "volume": volume,                        # 成交量
        "exchange": exchange,
        "change": change,
        "pct": pct,
    }


def display_name(code: str, product_table: dict | None = None) -> str:
    """合约中文名。商品期货行情自带名称；中金所没有，按品种名+月份拼。"""
    table = product_table if product_table is not None else PRODUCT_TABLE
    m = re.fullmatch(r"([A-Za-z]{1,2})(\d{3,4}|0)", code)
    if not m:
        return code
    prod, tail = m.group(1).upper(), m.group(2)
    pname = (table.get(prod) or {}).get("name") or prod
    if tail == "0":
        return pname + "主力"
    return pname + tail


def fetch_quote(code: str) -> dict:
    text = http_get(SINA_HQ_API + "nf_" + code, referer=SINA_REFERER)
    quote = parse_quote_line(text)
    if not quote:
        raise LookupError("未找到合约 %s 的行情（可能代码有误或已退市）" % code)
    # 中金所主力连续（XX0）的新浪原始报价不带名称、买卖盘常为 0；
    # 名称按品种表补成「沪深300主力」样式，空缺字段用成交量最大的
    # 月份合约快照兜底（只补空缺，不覆盖自身有效值）。
    if quote.get("exchange") == "中金所" and code.upper().endswith("0"):
        try:
            if not quote.get("name"):
                quote["name"] = display_name(code) or (code[:-1] + "主力")
            if not (quote.get("volume") and quote.get("oi")):
                siblings = fetch_product_quotes(quote.get("product", code[:-1]))
                dom = None
                for q in siblings.values():
                    if q["code"].upper().endswith("0") or not q.get("volume"):
                        continue
                    if dom is None or q["volume"] > dom["volume"]:
                        dom = q
                if dom:
                    for k in ("open", "high", "low", "settle", "presettle",
                              "bid", "ask", "bidvol", "askvol",
                              "volume", "oi"):
                        if not quote.get(k) and dom.get(k):
                            quote[k] = dom[k]
                    pre = quote.get("presettle") or 0
                    if pre:
                        quote["change"] = round(quote["last"] - pre, 6)
                        quote["pct"] = quote["change"] / pre * 100.0
        except Exception:                               # noqa: BLE001
            pass                                        # 回填失败仍返回原值
    return quote


def fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量取行情，新浪单次约可带 100 个代码。"""
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 40):
        batch = codes[i:i + 40]
        text = http_get(SINA_HQ_API + ",".join("nf_" + c for c in batch),
                        referer=SINA_REFERER)
        for line in text.splitlines():
            q = parse_quote_line(line)
            if q:
                out[q["code"]] = q
    return out


def contract_year_month(code: str):
    """从合约代码取交割年月（YYYYMM），如 SA2705 -> 202705；主力 XX0 返回 None。"""
    if re.fullmatch(r"[A-Za-z]{1,2}0", code):
        return None
    m = re.search(r"(\d{2})(\d{2})$", code)
    if not m:
        return None
    return (2000 + int(m.group(1))) * 100 + int(m.group(2))


def all_contract_codes(product: str, years_back: int = 7,
                       years_fwd: int = 1) -> list[str]:
    """枚举某品种**历史至今**出现过的全部月份合约代码（含已退市月份）。

    用于加权历史日K：主力月份逐月轮换，若只枚举"当前在交易"的合约，
    历史区间会漏掉当时的当月/次月合约（实测 2026-03 的 SA2605 当日成交
    115 万手，占绝对多数），合成出的成交量与价格都会严重失真。

    years_back 必须覆盖上游日K 的实际回溯深度：新浪日K 可回溯约 4~5 年
    （实测 CU/SA 能取到 2022 年）。曾因默认只回溯 3 年，导致 2022 年的
    当月合约（如 CU2204，当日成交 6.9 万手）根本没被枚举，合成的历史
    成交量被低估 800 倍。这里取 6 年留足余量。

    返回按交割年月升序的代码列表（不含主力连续 XX0）。上游对不存在/已退市
    的合约会返回空 K 线，调用方据此自然过滤。
    """
    product = product.upper()
    now = datetime.now()
    codes = []
    for y in range(now.year - max(1, years_back), now.year + years_fwd + 1):
        for m in range(1, 13):
            codes.append("%s%02d%02d" % (product, y % 100, m))
    return codes


def fetch_product_quotes(product: str) -> dict[str, dict]:
    """取某品种"全部挂牌合约 + 主力连续"的行情快照。

    合约清单不硬编码：按通行的"挂牌未来 12 个自然月"规则枚举
    （覆盖当年-1 到 +2 年），再叠加主力连续合约 XX0。
    """
    product = product.upper()
    now = datetime.now()
    codes = ["%s%02d%02d" % (product, y % 100, m)
             for y in range(now.year - 1, now.year + 3)
             for m in range(1, 13)]
    codes.append(product + "0")                       # 主力连续
    return fetch_quotes(codes)


def main_contract_active(product: str, today: str | None = None) -> bool:
    """该品种的主力合约是否仍在交易（用主力日线的最新日期判断）。

    行情快照对已停牌品种仍返回最后一次报价，光看行情会误判；日线
    最后日期才是可靠依据（如强麦 WH / 早籼稻 RI 停在 2022-2023 年）。
    """
    try:
        bars = fetch_kline(product + "0", "day")["bars"]
    except Exception:                                   # noqa: BLE001
        return False
    if not bars:
        return False
    last_day = bars[-1]["t"]
    ref = today or datetime.now().strftime("%Y-%m-%d")
    try:
        gap = (datetime.strptime(ref, "%Y-%m-%d")
               - datetime.strptime(last_day, "%Y-%m-%d")).days
    except ValueError:
        return False
    return gap <= 10                                     # 10 天内有过交易即视为在交易


def build_product_table(force: bool = False) -> dict:
    """构建全品种字典：{品种: {name, exchange, last, ...}}。

    品种中文名以"主力连续合约的实时名称"为权威来源（去掉"连续"二字），
    因此不需要维护任何中文名常量表——上游改名我们自动跟随；
    只有中金所行情不带名称，用 CFFEX_NAMES 兜底。
    """
    global PRODUCT_TABLE, PRODUCT_TABLE_AT
    with PRODUCT_TABLE_LOCK:
        if (not force and PRODUCT_TABLE
                and time.time() - PRODUCT_TABLE_AT < PRODUCT_TABLE_TTL):
            return PRODUCT_TABLE

        all_products = [p for plist in EXCHANGE_PRODUCTS.values() for p in plist]
        table: dict[str, dict] = {}

        for i in range(0, len(all_products), 12):
            batch = all_products[i:i + 12]
            # 一次请求拿 12 个品种的主力连续快照 → 中文名 + 最新价 + 涨跌
            quotes = fetch_quotes([p + "0" for p in batch])
            for p in batch:
                q = quotes.get(p + "0") or {}
                raw_name = q.get("name") or ""
                pname = re.sub(r"(连续|主力)$", "", raw_name).strip()
                if not pname:
                    pname = CFFEX_NAMES.get(p, "")
                table[p] = {
                    "product": p,
                    "name": pname or p,
                    "exchange": PRODUCT_EXCHANGE.get(p) or q.get("exchange") or "其它",
                    "last": q.get("last", 0.0),
                    "change": q.get("change", 0.0),
                    "pct": q.get("pct", 0.0),
                    "date": q.get("date", ""),
                    "tradeable": bool(q.get("last")),
                }

        # 用主力日线把"已长期停牌"的品种挑出来（强麦 / 早籼稻 / 粳稻 / 普麦 /
        # 郑棉纱 / 动力煤 等），它们在行情快照里仍挂着最后一次报价，
        # 但实际早已不再交易，留在列表里只会误导。
        pending = [p for p, v in table.items() if v["tradeable"] or v["name"] != p]
        for p in pending:
            v = table[p]
            v["tradeable"] = main_contract_active(p)
            if not v["tradeable"]:
                v["change"] = 0.0
                v["pct"] = 0.0

        PRODUCT_TABLE = table
        PRODUCT_TABLE_AT = time.time()
        return table


def _tq_to_item(q: dict, product: str, pname: str, tq: bool = True) -> dict:
    """把天勤 KQ.m / KQ.i 快照转成与新浪行情同构的行。"""
    last = float(q.get("last") or 0.0)
    pre = float(q.get("presettle") or 0.0) or last
    change = last - pre
    return {
        "code": product + "W",
        "name": pname + "指数(天勤)",
        "product": product,
        "isMain": False,
        "isWeighted": True,
        "isSynthetic": True,
        "source": WINDEX.SOURCE_TIANQIN,
        "underlying": q.get("underlying", ""),
        "time": "", "date": "",
        "open": float(q.get("open") or 0.0),
        "high": float(q.get("high") or 0.0),
        "low": float(q.get("low") or 0.0),
        "last": round(last, 4),
        "bid": float(q.get("bid") or 0.0),
        "ask": float(q.get("ask") or 0.0),
        "settle": 0.0,
        "presettle": round(pre, 4),
        "bidvol": 0, "askvol": 0,
        "oi": int(q.get("oi") or 0),
        "volume": int(q.get("volume") or 0),
        "exchange": "",
        "change": round(change, 4),
        "pct": round(change / pre * 100.0, 6) if pre else 0.0,
        "members": 0,
        "components": [],
    }


def is_weighted_code(code: str) -> bool:
    return bool(WEIGHTED_SYMBOL_RE.match(str(code or "").upper()))


def _weight_mode_of(code: str) -> str:
    """加权代码后缀 → 权重口径。XXW = 持仓量。"""
    return "oi"


def fetch_weighted_quote(code: str) -> dict:
    """XXW 加权指数行情：由该品种全部在交易合约实时合成（不直连上游）。"""
    product = code[:-1].upper()
    sym = fetch_symbols(product, weight_mode=_weight_mode_of(code))
    row = next((it for it in sym["items"] if it.get("isWeighted")), None)
    if not row:
        raise LookupError("无法合成 %s 的加权指数（该品种在交易合约不足 2 个）" % product)
    now = datetime.now()
    return dict(row, code=code,
                time=now.strftime("%H%M%S"),
                date=now.strftime("%Y-%m-%d"))


def fetch_weighted_timeshare(code: str, weight_mode: str = "oi") -> dict:
    """XXW 加权分时：各月份合约分时按时间对齐后加权。"""
    product = code[:-1].upper()
    sym = fetch_symbols(product, weight_mode=weight_mode)
    members = [it for it in sym["items"]
               if not it.get("isWeighted") and not it.get("isMain")]
    if not members:
        raise LookupError("无法合成 %s 的加权分时" % product)

    # 只取权重靠前的若干合约，减少请求数（覆盖 95% 权重即可）
    members = _top_members(members, weight_mode)
    sets, weights = [], []
    for m in members:
        try:
            ts = fetch_timeshare(m["code"])
        except Exception:                               # noqa: BLE001
            continue
        pts = ts.get("points") or []
        if pts:
            sets.append(pts)
            weights.append(_member_weight(m, weight_mode))
    if not sets:
        raise LookupError("加权分时无可用成分数据")

    pts = WINDEX.synth_index_timeshare_weighted(sets, weights)
    # 时段轴取权重最大那个合约的（同一品种各合约时段一致）
    slots = []
    try:
        slots = get_session_slots(members[0]["code"])
    except Exception:                                   # noqa: BLE001
        slots = []
    base = next((it for it in sym["items"] if it.get("isWeighted")), None) \
        or next((it for it in sym["items"] if not it.get("isWeighted")), {})
    # 与普通分时结构对齐：前端图例用到 preClose / day 字段。
    # 涨跌基准用「加权昨结算」（加权行自带），而非单个合约的昨结。
    pre_close = float((base or {}).get("presettle") or 0.0)
    day = str(base.get("date") or "") or datetime.now().strftime("%Y-%m-%d")
    if not pre_close and pts:
        pre_close = pts[0]["c"]
    return {
        "symbol": code,
        "name": sym["productName"] + "指数",
        "preClose": pre_close,
        "day": day,
        "presettle": pre_close,
        "points": pts,
        "slots": slots,
        "isWeighted": True,
        "members": len(sets),
    }


def _member_weight(m: dict, mode: str) -> float:
    return float((m.get("volume") if mode == "vol" else m.get("oi")) or 0.0)


def _top_members(members: list[dict], mode: str, cover: float = 0.97) -> list[dict]:
    """按权重降序取前若干个，累计覆盖 cover 即停（至少 3 个，最多 8 个）。"""
    ordered = sorted(members, key=lambda x: -_member_weight(x, mode))
    total = sum(_member_weight(x, mode) for x in ordered) or 1.0
    out, acc = [], 0.0
    for m in ordered:
        out.append(m)
        acc += _member_weight(m, mode)
        if (acc / total >= cover and len(out) >= 3) or len(out) >= 8:
            break
    return out


def fetch_weighted_kline(code: str, period: str,
                         weight_mode: str = "oi") -> dict:
    """XXW 加权 K 线：各月份合约同周期 K 线按时间戳对齐后加权。

    权重口径按周期区分（很关键）：
      * 日线（以及由日线合成的周/月/年）：用**逐根 K 线自身的持仓量**动态加权。
        历史日K 必须用动态权重，因为主力月份会随交割轮换 —— 用"今天的持仓量"
        当历史权重会漏掉早已退市的当月合约（如 2026-03 的 SA2605 当日成交
        115 万手却是别人的零头），实测成交量被低估 200 倍。
        因此这里要枚举**全部**合约代码（含已退市的月份），不能只取当前 Top-N。
      * 分钟线：用当刻持仓量快照固定加权（同一交易日内权重稳定，与分时口径一致）。
    """
    product = code[:-1].upper()
    src_period = "day" if period in ("day", "week", "month", "year") else period

    sym = fetch_symbols(product, weight_mode=weight_mode)
    pname = sym["productName"]

    if src_period == "day":
        # 历史日K：枚举全部上市过/在交易的全部月份合约（含已退市），动态 OI 加权
        codes = all_contract_codes(product)
        series = []
        for c in codes:
            try:
                k = fetch_kline(c, "day")
            except Exception:                           # noqa: BLE001
                continue
            if k.get("bars"):
                series.append(k["bars"])
        if not series:
            raise LookupError("加权 K 线无可用成分数据")
        bars = WINDEX.synth_index_kline(series, None, mode="auto")
    else:
        # 分钟线：Top-N 成分 + 当刻持仓量固定权重（与分时一致）
        members = [it for it in sym["items"]
                   if not it.get("isWeighted") and not it.get("isMain")]
        if not members:
            raise LookupError("无法合成 %s 的加权 K 线" % product)
        members = _top_members(members, weight_mode)
        series, weights = [], []
        for m in members:
            try:
                k = fetch_kline(m["code"], src_period)
            except Exception:                           # noqa: BLE001
                continue
            if k.get("bars"):
                series.append(k["bars"])
                weights.append(_member_weight(m, weight_mode))
        if not series:
            raise LookupError("加权 K 线无可用成分数据")
        bars = WINDEX.synth_index_kline(series, weights, mode="fixed")

    # 周/月/年由前端用日K合成（与单合约一致），这里统一只回日K
    return {
        "code": code, "name": pname + "指数",
        "period": src_period,
        "bars": bars, "isWeighted": True,
    }


def fetch_symbols(product: str = DEFAULT_PRODUCT,
                  anchor: str | None = None,
                  weight_mode: str = "oi",
                  tq_fallback: bool = False) -> dict:
    """枚举同品种全部**在交易**的挂牌合约 + 主力连续 + 加权指数。

    过滤规则（已验证与新浪页面一致）：
      1) 代码交割年月 >= 当前年月（已交割月份直接排除，如 SA2408）
      2) 行情日期在最近 7 个自然日内（排除停牌 / 摘牌）
      3) 主力连续 XX0 永远保留（它没有交割月份）
      4) 额外合成一行「加权指数」XXW，置顶（详见 weighted_index.py）

    weight_mode: "oi" 持仓量加权（默认）/ "vol" 成交量加权 /
                 "tianqin" 改用天勤官方 KQ.i 指数
    tq_fallback: 新浪缺数据时是否尝试天勤
    """
    product = product.upper()
    if not PRODUCT_RE.match(product):
        raise ValueError("品种代码不合法")

    raw = fetch_product_quotes(product)
    table = build_product_table()
    meta = table.get(product, {})
    pname = meta.get("name") or product

    now = datetime.now()
    cur_ym = now.year * 100 + now.month

    # 以"最新交易日"为基准排除刚摘牌、快照未更新的合约
    latest = max((q["date"] for q in raw.values() if q["date"]), default="")
    cutoff = ""
    if latest:
        try:
            cutoff = (datetime.strptime(latest, "%Y-%m-%d")
                      - timedelta(days=7)).strftime("%Y-%m-%d")
        except ValueError:
            cutoff = ""

    items = []
    for code, q in raw.items():
        ym = contract_year_month(code)
        if ym is not None and ym < cur_ym:
            continue                                     # 已交割的月份
        if ym is None and not code.upper().endswith("0"):
            continue                                     # 非法代码
        if cutoff and q["date"] and q["date"] < cutoff:
            continue                                     # 无有效报价（摘牌/停牌）
        items.append({
            "code": code,
            "name": q["name"] or display_name(code, table),
            "last": q["last"], "change": q["change"], "pct": q["pct"],
            "presettle": q["presettle"],
            "open": q["open"], "high": q["high"], "low": q["low"],
            "volume": q["volume"], "oi": q["oi"],
            "date": q["date"],
            "isMain": bool(re.fullmatch(r"[A-Za-z]{1,2}0", code)),
            "isWeighted": False,
        })

    # ---- 算出「该品种全部真实月份合约」的加权指数 ----
    # 只喂真实月份合约（已在上面过滤掉已交割/停牌的）；主力连续 XX0 不参与，
    # 否则主力所在月份的权重会被算两遍。
    weighted = WINDEX.build_weighted_index(
        [it for it in items if not it["isMain"]], weight_mode)

    # ---- 次选：天勤官方指数 / 主连（配置了快期账号才生效） ----
    tq_main_row = None
    if weight_mode == WINDEX.SOURCE_TIANQIN or tq_fallback:
        tq = WINDEX.tq_quote_set(product, meta.get("exchange") or "")
        if tq:
            if tq.get("index"):
                weighted = _tq_to_item(tq["index"], product, pname)
            if tq.get("main"):
                tq_main_row = _tq_to_item(tq["main"], product, pname)
                tq_main_row["code"] = product + "0"
                tq_main_row["name"] = (pname + "主连(天勤)")
                tq_main_row["isWeighted"] = False
                tq_main_row["isMain"] = True
    if weighted:
        weighted["code"] = product + "W"
        weighted["name"] = pname + ("指数" if weighted.get("source") != "tianqin"
                                    else "指数(天勤)")
        weighted["product"] = product
        weighted["exchange"] = meta.get("exchange") or ""
        weighted["isWeighted"] = True
        weighted["isSynthetic"] = True
        items.insert(0, weighted)

    # 天勤主连覆盖新浪的 XX0（新浪那份字段口径在 CFFEX 上不稳）
    if tq_main_row:
        items = [it for it in items
                 if it["code"].upper() != tq_main_row["code"].upper()]
        items.append(tq_main_row)

    # 排序：加权指数置顶 → 主力连续 → 其余按交割月递增
    items.sort(key=lambda x: (0 if x.get("isWeighted") else
                              (1 if x["isMain"] else 2),
                             contract_year_month(x["code"]) or 0))

    # 主力标记：优先 XX0；没有则退化为持仓量最大的月份合约
    # 注意：加权指数行不参与「主力」竞争
    if not any(it["isMain"] for it in items
               if not it.get("isWeighted")) and items:
        cands = [it for it in items if not it.get("isWeighted")]
        if cands:
            top = max(cands, key=lambda x: x["oi"])
            for it in items:
                it["isMain"] = (not it.get("isWeighted")
                                and it["code"] == top["code"])

    main = next((it["code"] for it in items
                 if it["isMain"] and not it.get("isWeighted")), "")

    if not pname or pname == product:
        anchor_name = (raw.get(anchor or "") or {}).get("name", "") if anchor else ""
        pname = re.sub(r"\d+$", "", anchor_name) or product

    return {
        "product": product,
        "productName": pname,
        "exchange": meta.get("exchange") or next(
            (q["exchange"] for q in raw.values() if q.get("exchange")), ""),
        "latestTradingDay": latest,
        "main": main,
        "weightMode": weight_mode,
        "count": len(items),
        "items": items,
    }


def fetch_products() -> dict:
    """全品种树：按交易所分组，供左侧品种列表使用。"""
    table = build_product_table()
    groups: dict[str, list] = {}
    for p, meta in table.items():
        groups.setdefault(meta["exchange"], []).append({
            "product": p,
            "name": meta["name"],
            "last": meta["last"],
            "change": meta["change"],
            "pct": meta["pct"],
            "date": meta["date"],
            "main": p + "0",
            "tradeable": meta["tradeable"],
        })
    order = ["中金所", "上期所", "大商所", "郑商所", "广期所", "其它"]
    out = []
    for ex in order:
        lst = groups.pop(ex, None)
        if not lst:
            continue
        lst.sort(key=lambda x: x["product"])
        out.append({"exchange": ex, "count": len(lst), "items": lst})
    for ex in sorted(groups):
        lst = sorted(groups[ex], key=lambda x: x["product"])
        out.append({"exchange": ex, "count": len(lst), "items": lst})
    return {
        "count": sum(g["count"] for g in out),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "groups": out,
    }

def fetch_timeshare(code: str) -> dict:
    """当日分时。返回 {preClose, points:[{t,c,avg,v,oi,day}]}

    注意：极冷门合约（如胶合板 BB）当日无成交时，上游会返回 `var t=(null);`，
    解析结果为 None，这里统一归一化成"0 个点"，让前端走"暂无分时数据"分支，
    而不是把 TypeError 抛到 HTTP 层。
    """
    url = SINA_FUT_API + "getMinLine?symbol=" + urllib.parse.quote(code)
    rows = parse_jsonp(http_get(url))
    if not rows or not isinstance(rows, (list, tuple)):
        rows = []
    points = []
    pre_close = 0.0
    trade_day = ""
    for r in rows:
        if not isinstance(r, list) or len(r) < 3:
            continue
        if len(r) >= 6:
            pre_close = num(r[5]) or pre_close
        if len(r) > 6 and not trade_day:
            trade_day = str(r[6])
        points.append({
            "t": str(r[0]),
            "c": num(r[1]),
            "avg": num(r[2]),
            "v": numi(r[3]),
            "oi": numi(r[4]),
            "day": str(r[6]) if len(r) > 6 else "",
        })
    if not pre_close and points:
        pre_close = points[0]["c"]
    return {
        "symbol": code,
        "preClose": pre_close,
        "day": trade_day,
        "count": len(points),
        "points": points,
    }


PERIOD_MINUTES = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60, "120": 120}


def minute_key(hhmm: str) -> int | None:
    """把 HH:MM 映射成"交易日内序号"，让夜盘排在日盘之前。

    21:00 起为 60，23:59 为 239，次日 00:00 为 240，09:00 为 780，
    15:00 为 1140 —— 与真实开盘先后一致，便于跨日的分钟点统一排序。
    """
    if not hhmm or len(hhmm) < 5:
        return None
    try:
        total = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except ValueError:
        return None
    return total - 1200 if total >= 20 * 60 else total + 240


def minute_from_key(key: int) -> str:
    """minute_key 的逆运算。"""
    total = key + 1200 if key < 240 else key - 240
    total %= 24 * 60
    return "%02d:%02d" % (total // 60, total % 60)


def fetch_session_slots(code: str) -> list[str]:
    """推导该合约一个完整交易日的时间轴（分钟粒度）。

    新浪分钟 K 线以"分钟结束时刻"标注，且一次覆盖最近数个交易日，
    把出现过的分钟点按交易日内顺序排好、再整体前移一分钟，即可还原
    完整时段（如纯碱：夜盘 21:00-22:59 + 日盘 09:00-14:59 共 345 分钟）。
    全程由数据推导，不依赖任何交易所时段硬编码表。
    """
    bars = fetch_kline(code, "1")["bars"]
    keys = set()
    for b in bars:
        t = str(b.get("t", ""))
        if len(t) < 16:
            continue
        k = minute_key(t[11:16])
        if k is not None:
            keys.add(k)
    if not keys:
        return []
    return [minute_from_key(k - 1) for k in sorted(keys)]


def fetch_kline(code: str, period: str) -> dict:
    """K 线。period: 1/5/15/30/60/120 分钟 或 day"""
    if period == "day":
        url = SINA_FUT_API + "getDailyKLine?symbol=" + urllib.parse.quote(code)
        rows = parse_jsonp(http_get(url))
        bars = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            bars.append({
                "t": str(r.get("d", "")),
                "o": num(r.get("o")), "h": num(r.get("h")),
                "l": num(r.get("l")), "c": num(r.get("c")),
                "v": numi(r.get("v")), "oi": numi(r.get("p")),
                "s": num(r.get("s")),
            })
        return {"symbol": code, "period": "day", "bars": bars}

    if period not in PERIOD_MINUTES:
        raise ValueError("不支持的周期：%s" % period)

    url = (SINA_FUT_API + "getFewMinLine?symbol=" + urllib.parse.quote(code)
           + "&type=" + period)
    rows = parse_jsonp(http_get(url))
    bars = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        bars.append({
            "t": str(r.get("d", "")),
            "o": num(r.get("o")), "h": num(r.get("h")),
            "l": num(r.get("l")), "c": num(r.get("c")),
            "v": numi(r.get("v")), "oi": numi(r.get("p")),
            "s": 0.0,
        })

    # 上游单次最多约 1023 根：分钟线要按时间正序保留**最近**的一段，
    # 否则会把最新的行情截掉（曾导致交易时段推导不完整）。
    if len(bars) >= MINUTE_KLINE_LIMIT:
        bars = bars[-MINUTE_KLINE_LIMIT:]

    return {"symbol": code, "period": period, "bars": bars}


# --------------------------------------------------------------------------- #
# 业务层（带缓存）
# --------------------------------------------------------------------------- #

def get_quote(code: str) -> dict:
    return CACHE.get_or("quote:" + code, tick_ttl(2.0, 20.0),
                        lambda: fetch_quote(code))


# ---- 加权指数（XXW）系列：缓存略长，因为要聚合成分合约 ----

def get_weighted_quote_cached(code: str) -> dict:
    return CACHE.get_or("wquote:" + code, tick_ttl(5.0, 60.0),
                        lambda: fetch_weighted_quote(code))


def get_weighted_timeshare_cached(code: str) -> dict:
    return CACHE.get_or("wts:" + code, tick_ttl(10.0, 120.0),
                        lambda: fetch_weighted_timeshare(code))


def get_weighted_kline_cached(code: str, period: str) -> dict:
    fast, slow = (60.0, 600.0) if period in ("day", "week", "month", "year") \
        else (30.0, 300.0)
    return CACHE.get_or("wk:%s:%s" % (code, period), tick_ttl(fast, slow),
                        lambda: fetch_weighted_kline(code, period))


def get_symbols(product: str, anchor: str | None,
                weight_mode: str = "oi", tq_fallback: bool = False) -> dict:
    key = "symbols:%s:%s:%d" % (product.upper(), weight_mode, int(tq_fallback))
    return CACHE.get_or(key, tick_ttl(8.0, 60.0),
                        lambda: fetch_symbols(product, anchor,
                                              weight_mode, tq_fallback))


def get_products() -> dict:
    """全品种树（覆盖国内四家交易所 + 广期所），缓存 30 分钟。"""
    return CACHE.get_or("products", tick_ttl(1800.0, 21600.0),
                        fetch_products)


def get_timeshare(code: str) -> dict:
    data = CACHE.get_or("ts:" + code, tick_ttl(5.0, 120.0),
                        lambda: fetch_timeshare(code))
    # 附带完整交易时段，供前端把分时曲线按真实时间轴定位（不再随时间被拉伸）
    try:
        slots = get_session_slots(code)
    except Exception:                                   # noqa: BLE001
        slots = []
    if slots:
        data = dict(data, slots=slots)
    return data


def get_session_slots(code: str) -> list[str]:
    """完整交易时段，变化极慢，缓存 30 分钟（休市 6 小时）。"""
    return CACHE.get_or("slots:" + code, tick_ttl(1800.0, 21600.0),
                        lambda: fetch_session_slots(code))


def get_kline(code: str, period: str) -> dict:
    fast, slow = {
        "1": (15.0, 300.0), "5": (20.0, 300.0), "15": (30.0, 300.0),
        "30": (40.0, 300.0), "60": (60.0, 300.0), "120": (60.0, 300.0),
        "day": (60.0, 600.0),
    }.get(period, (30.0, 300.0))
    return CACHE.get_or("k:%s:%s" % (code, period), tick_ttl(fast, slow),
                        lambda: fetch_kline(code, period))


# --------------------------------------------------------------------------- #
# HTTP 服务
# --------------------------------------------------------------------------- #

class PanelHTTPServer(ThreadingHTTPServer):
    """关闭 allow_reuse_address 的多实例复用。

    标准库 HTTPServer 默认 allow_reuse_address = 1，在 Windows 上会让
    两个进程绑定同一端口而不报错（表现为双监听、旧实例抢答、改了代码不生效）。
    这里显式关掉：端口被占就直接抛 OSError，由 main() 的 pick_port 提前规避。
    """
    allow_reuse_address = False
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "FuturesPanel/1.0"
    protocol_version = "HTTP/1.1"

    # 关闭默认的 stderr 日志刷屏
    def log_message(self, fmt, *args):      # noqa: A003
        if VERBOSE:
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(),
                                            fmt % args))

    # ---------------- 工具 ---------------- #

    def _send(self, status: int, body: bytes, ctype: str,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        # allow_nan=False：宁可抛错落到 502，也不把裸 NaN/Infinity 发给前端
        # （裸 NaN 不是合法 JSON，浏览器 res.json() 会直接失败）。
        # 真出现时统一降级为 null，保证响应始终可解析。
        try:
            body = json.dumps(payload, ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
        except ValueError:
            body = json.dumps(_json_safe(payload), ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _ok(self, data) -> None:
        self._json({"ok": True, "ts": int(time.time() * 1000), "data": data})

    def _err(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": str(message)}, status)

    # ---------------- 路由 ---------------- #

    def do_GET(self):                                     # noqa: N802
        self._route()

    def do_HEAD(self):                                    # noqa: N802
        self._route()

    def _route(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        def arg(name: str, default: str = "") -> str:
            return (query.get(name) or [default])[0].strip()

        try:
            if path.startswith("/api/"):
                return self._api(path, arg)

            if path in ("/", "/index.html", "/app.html"):
                return self._static(panel_html_path())

            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")

            # 其他静态资源（同目录白名单，防目录穿越）
            rel = path.lstrip("/").replace("\\", "/")
            if ".." in rel:
                return self._err("非法路径", 400)
            full = os.path.normpath(os.path.join(APP_DIR, rel))
            if not full.startswith(os.path.normpath(APP_DIR)):
                return self._err("非法路径", 400)
            if os.path.isfile(full):
                return self._static(full)

            return self._err("Not Found: " + path, 404)
        except LookupError as exc:
            return self._err(exc, 404)
        except ValueError as exc:
            return self._err(exc, 400)
        except Exception as exc:                          # noqa: BLE001
            return self._err("%s: %s" % (type(exc).__name__, exc), 502)

    def _api(self, path: str, arg) -> None:
        if path == "/api/health":
            return self._ok({"status": "up", "trading": is_trading_now(),
                             "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

        if path == "/api/quote":
            code = self._need_symbol(arg)
            if is_weighted_code(code):
                return self._ok(get_weighted_quote_cached(code))
            return self._ok(get_quote(code))

        if path == "/api/products":
            return self._ok(get_products())

        if path == "/api/symbols":
            product = arg("product", DEFAULT_PRODUCT).upper()
            anchor = arg("symbol") or None
            if not PRODUCT_RE.match(product):
                return self._err("品种代码不合法")
            wmode = (arg("weight") or "oi").lower()
            if wmode not in ("oi", "vol", "tianqin"):
                wmode = "oi"
            return self._ok(get_symbols(product, anchor, wmode,
                                        arg("tq") == "1"))

        # 天勤（快期）连接状态：前端据此决定是否显示「官方指数」
        if path == "/api/tq/status":
            return self._ok(WINDEX.tq_status())

        if path == "/api/timeshare":
            code = self._need_symbol(arg)
            if is_weighted_code(code):
                return self._ok(get_weighted_timeshare_cached(code))
            return self._ok(get_timeshare(code))

        if path == "/api/kline":
            code = self._need_symbol(arg)
            period = arg("period", "day").lower()
            if is_weighted_code(code):
                return self._ok(get_weighted_kline_cached(code, period))
            return self._ok(get_kline(code, period))

        return self._err("未知接口：" + path, 404)

    @staticmethod
    def _need_symbol(arg) -> str:
        code = arg("symbol", DEFAULT_SYMBOL).upper()
        if not (SYMBOL_RE.match(code) or MAIN_SYMBOL_RE.match(code)
                or WEIGHTED_SYMBOL_RE.match(code)):
            raise ValueError("合约代码不合法：" + code)
        return code

    def _static(self, full: str) -> None:
        if not os.path.isfile(full):
            return self._err("未找到文件：" + os.path.basename(full), 404)
        ext = os.path.splitext(full)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".png": "image/png",
        }.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)


VERBOSE = False


def _json_safe(obj):
    """递归把 NaN / ±Infinity 换成 None，保证可被严格 JSON 序列化。"""
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #

def pick_port(start: int, tries: int = 30) -> int:
    """从 start 起找一个能真正独占绑定的端口。

    ⚠ Windows 陷阱：探测时**绝不能设 SO_REUSEADDR**。
    Windows 的 SO_REUSEADDR 语义与 Linux 不同——它允许两个 socket
    绑定到完全相同的 (addr, port)，于是"探测可用"永远为真，
    结果两个进程同时 LISTEN 在 8686：新进程以为换好了端口、
    旧进程还在响应请求，表现为"改了代码重启却没生效 / 数据是旧的"。
    （本机曾真的出现两个监听进程，排查耗时很久。）

    这里改用不带 SO_REUSEADDR 的裸 bind 探测：Windows 下若端口已被
    占用会明确报 WSAEADDRINUSE，探测结果才可信。
    """
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("端口 %d~%d 全部被占用" % (start, start + tries))


def port_in_use(port: int) -> bool:
    """该端口是否已被别的进程监听（用于启动前友好提示）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def self_check(symbol: str) -> None:
    """启动前拉一次数据，让用户立刻知道网络是否通。"""
    tag = "交易中" if is_trading_now() else "休市"
    print("  · 当前状态：%s" % tag)
    try:
        q = fetch_quote(symbol)
        print("  · 行情连通：%s  %s  %+.1f (%+.2f%%)  更新于 %s %s"
              % (q["name"], q["last"], q["change"], q["pct"],
                 q["date"], q["time"]))
    except Exception as exc:                              # noqa: BLE001
        print("  ! 行情接口异常：%s: %s" % (type(exc).__name__, exc))
        print("    面板仍会启动，请检查网络后刷新页面。")
    try:
        sym = fetch_symbols(symbol[:2] or DEFAULT_PRODUCT, symbol)
        print("  · 合约列表：共 %d 个挂牌合约，主力 = %s"
              % (sym["count"], sym["main"] or "-"))
    except Exception as exc:                              # noqa: BLE001
        print("  ! 合约列表接口异常：%s" % exc)


def main() -> int:
    global VERBOSE

    try:
        sys.stdout.reconfigure(encoding="utf-8")          # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")          # type: ignore[attr-defined]
    except Exception:                                     # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(
        description="纯碱期货行情面板（Python + HTML，数据源：新浪财经）")
    ap.add_argument("--symbol", default=DEFAULT_SYMBOL, help="默认合约，如 SA2701")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印访问日志")
    args = ap.parse_args()

    symbol = args.symbol.upper()
    if not (SYMBOL_RE.match(symbol) or MAIN_SYMBOL_RE.match(symbol)):
        print("合约代码不合法：%s" % symbol)
        return 2

    VERBOSE = args.verbose
    port = pick_port(args.port)
    url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "") else args.host, port)

    print("=" * 64)
    print("  国内期货行情面板  ·  数据源：新浪财经")
    print("=" * 64)
    print("  · 默认合约：%s" % symbol)
    if IS_FROZEN:
        print("  · 运行方式：单文件 EXE（资源目录 %s）" % BUNDLE_DIR)
    else:
        print("  · 运行方式：源码（%s）" % APP_DIR)
    try:
        _tq = WINDEX.tq_status()
        if not _tq.get("installed"):
            print("  · 天勤（快期）：未安装 tqsdk，仅本地加权可用")
        elif _tq.get("configured"):
            _ext = "外置" if _tq.get("configExternal") else "内置"
            print("  · 天勤（快期）：已启用（%s配置）" % _ext)
        else:
            print("  · 天勤（快期）：未配置，仅本地加权可用")
    except Exception:                                     # noqa: BLE001
        pass
    if port != args.port:
        print("  · 端口 %d 被占用，已改用 %d" % (args.port, port))
    self_check(symbol)
    print("-" * 64)
    print("  面板地址：%s" % url)
    if IS_FROZEN:
        print("  提示：把 tianqin.json 放到本 EXE 同目录，可覆盖内置账号")
    print("  按 Ctrl+C 退出")
    print("=" * 64)

    try:
        httpd = PanelHTTPServer((args.host, port), Handler)
    except OSError as exc:
        print("  ! 端口 %d 绑定失败：%s" % (port, exc))
        print("    可能有另一个实例正在运行，请换端口：--port %d" % (port + 1))
        return 3
    httpd.daemon_threads = True

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
