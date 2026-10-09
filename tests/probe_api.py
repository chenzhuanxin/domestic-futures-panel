# -*- coding: utf-8 -*-
"""探测新浪财经期货接口可用性与字段格式"""
import urllib.request, urllib.error, json, re, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 禁用系统代理（本机代理端口会变，直连更稳）
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
urllib.request.install_opener(opener)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def get(url, referer=None, timeout=12):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    if referer:
        req.add_header("Referer", referer)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def show(title, url, referer=None, limit=400):
    print("=" * 70)
    print("[%s]" % title)
    print("  URL:", url)
    try:
        t = get(url, referer)
        print("  长度:", len(t))
        print("  前 %d 字符:" % limit)
        print(t[:limit])
    except Exception as e:
        print("  !! 失败:", type(e).__name__, e)
    print()


# 1. 实时行情
show("实时行情 hq.sinajs.cn", "https://hq.sinajs.cn/list=nf_SA2701",
     referer="https://finance.sina.com.cn")

# 2. 分时
show("分时 getMinLine",
     "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getMinLine?symbol=SA2701")

# 3. 1 分钟K
show("1分钟K getFewMinLine type=1",
     "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getFewMinLine?symbol=SA2701&type=1")

# 4. 5 分钟K
show("5分钟K getFewMinLine type=5",
     "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getFewMinLine?symbol=SA2701&type=5")

# 5. 日K
show("日K getDailyKLine",
     "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getDailyKLine?symbol=SA2701")

# 6. 批量合约
show("批量合约行情（枚举）",
     "https://hq.sinajs.cn/list=nf_SA2601,nf_SA2605,nf_SA2609,nf_SA2701,nf_SA2705,nf_SA2709",
     referer="https://finance.sina.com.cn")

# 7. 东财备选：实时
show("东财 push2 实时",
     "https://push2.eastmoney.com/api/qt/stock/get?secid=115.SA2701&fields=f57,f58,f43,f44,f45,f46,f47,f48,f60,f107,f169,f170,f171,f108",
     referer="https://quote.eastmoney.com/")

# 8. 东财 K 线
show("东财 kline",
     "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=115.SA2701&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=0&end=20500101&lmt=20",
     referer="https://quote.eastmoney.com/")
