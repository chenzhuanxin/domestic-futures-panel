# 国内期货行情面板（Python + HTML，全品种）

一个**单机运行**的**国内全品种**期货行情面板，默认展示**纯碱主力连续（SA0）**，
覆盖**中金所 / 上期所 / 大商所 / 郑商所 / 广期所**共 79 个品种，
数据来自**新浪财经期货公开接口**，无需注册、无需 Token、无需安装任何第三方库。

![预览](https://img.shields.io/badge/Python-3.8%2B-blue) ![依赖](https://img.shields.io/badge/%E4%BE%9D%E8%B5%96-%E9%9B%B6-green)

## 下载 / 在线文档

| 入口 | 地址 |
|---|---|
| **⬇ 下载 EXE（免安装，推荐）** | [Releases · v1.0.0](https://github.com/chenzhuanxin/domestic-futures-panel/releases/latest) |
| 🌐 **在线主页** | https://chenzhuanxin.github.io/domestic-futures-panel/ |
| 📖 **使用说明** | https://chenzhuanxin.github.io/domestic-futures-panel/usage.html |
| 🔌 **数据源说明** | https://chenzhuanxin.github.io/domestic-futures-panel/datasource.html |

> 附件名 `futures-panel-v1.0.0.exe`（约 74 MB）。
> SHA-256：`18d7727220c5a00d61d83ee8473e83da6142e6478d96f2bdaa0a12a3b935bab3`

## 功能

- **实时行情**：最新价、涨跌（相对昨结算）、今开/最高/最低/昨结、成交量、持仓量、买一/卖一
- **SAR 多空双色点**：多头点（红）画在 K 线下方、空头点（绿）画在 K 线上方，
  图例同步显示当前多空状态
- **全品种系统**（左侧栏）：
  - 覆盖国内五家交易所 79 个品种（含股指、国债），按交易所分组、支持中文名/代码搜索；
  - 品种中文名自动取自主力连续合约的实时行情（上游改名自动跟随），
    已停牌品种（如强麦、早籼稻）通过主力日K最后交易日期自动识别并置灰标注；
  - 点击品种即切换到该品种主力连续合约（XX0），右侧合约列表同步刷新；
  - 中金所 50 字段行情布局单独解析（开/高/低/最新/成交/持仓口径与商品期货不同），
    主力连续缺失的字段用成交量最大的月份合约自动补齐。
- **主图**：
  - 分时图（价格线 + 均价线 + 昨收基准 + 百分比轴）
  - K 线蜡烛图 + MA / SAR / BOLL / EXPMA / BBIBOLL 可切换
- **周期**：分时、1分、5分、15分、30分、60分、120分、日K、周K、月K、年K
  （周K / 月K / 年K 由日K在前端合成，成交量求和、持仓量取期末值）
- **副图一**：成交量柱（红涨绿跌）+ 持仓量曲线（上下分区显示）
- **副图二**：MACD / KDJ / RSI / BOLL / WR / DMI 一键切换
  （选 BOLL 时主图叠加布林带，副图二显示上中下三轨）
- **分时横纵轴自适应**（与新浪财经分时图同款做法）：
  - 横轴把**整段交易时段**摊满全宽，行情走到哪画到哪——刚开盘只有几十个点时
    曲线只占左侧一小段，不会被拉伸铺满；夜盘 / 上午 / 下午小节分界自动画虚线分隔；
  - 纵轴以**昨结算为中心上下对称**，档位取整数百分比（±0.2% / ±0.5% / ±1% …），
    行情波动越大档位自动越高，价格始终完整落在轴内；
  - 交易时段不靠硬编码：后端用 1 分钟 K 线还原该合约的完整分钟序列
    （如纯碱 = 夜盘 21:00-22:59 + 日盘 09:00-14:59 共 345 格），换任何品种都自动适配。
- **同品种合约列表**：右侧自动枚举该品种全部挂牌合约，标注主力（持仓量最大），点击即切换
- **加权指数（∑ 置顶）/ 指数口径切换**：
  - 新浪没有真正的加权指数（XX99/XX888 实测为空），故由**全部在交易月份合约按持仓量
    加权**本地合成：`last = Σ(价×持仓)/Σ持仓`，开高低/昨结同口径加权，量/仓求和；
  - 点击 ∑ 行可看加权指数的**分时 / 1分~日K 全周期**（各合约分钟线按时间对齐后加权，
    缺失分钟用前收盘价填充，周/月/年K 继续由加权日K 前端合成）；
  - **加权日K 为全量历史**（约 1,600~2,000 根、回溯 7 年至 2018 年）：
    历史日K 逐根枚举**当时上市过的全部月份合约**、按**每根 K 线自身的持仓量动态加权**，
    因此能正确覆盖历史上轮换过的主力月份（详见下方算法说明）；
  - 加权行权重明细（各合约权重%）随接口返回，可核查；72 个在交易品种全部支持；
  - 右侧「同品种合约」标题栏有 **仓权 / 量权 / 天勤** 三档分段按钮，可实时切换指数口径
    （选择写入 localStorage，刷新后保持；天勤未配置时该档自动置灰）；
  - **天勤（快期）官方指数/主连**：在 `tianqin.json` 填入快期账号并置 `enabled=true`
    后重启，选「天勤」档即返回官方 `KQ.i`（指数）/ `KQ.m`（主连）数据，
    `/api/tq/status` 查看连接状态。实测天勤官方纯碱指数与本地持仓量加权指数
    偏差 < 0.05%（5 家交易所交叉验证），可作为算法正确性的外部基准。
- **K 线全量显示 + 缩放平移**：
  - **所有周期默认显示全量**：分时按整段交易时段铺满，1分~120分 / 日 / 周 / 月 / 年
    默认从最新一根起把**全部可用历史**画满，不再默认截断成最近 120 根；
  - 缩放平移：**滚轮**放大缩小、**鼠标拖动**左右平移、**方向键**微调、`+`/`-` 缩放、
    `R` 复位、**全览**按钮一键看全量；
  - **触屏手势**：单指左右平移、双指捏合拉伸/压缩（锚定手指中心），
    `touch-action: none` 防止页面滚动抢走手势，手机/平板可直接操作。
- **底部数据说明（可折叠 · 默认折叠）**：`#chartFoot` 面板汇总**操作方式 /
  数据范围 / 加权指数口径 / 数据源与声明**四栏，点击标题栏（或回车/空格）展开收起，
  展开状态写入 localStorage 记忆；**底部常驻署名：设计：公歧子　微信：gongqizi0**
  （点击微信号一键复制）。
- **交互**：滚轮缩放、拖动平移、触屏手势、方向键/+- 键、十字光标数据浮窗、复位/全览
- **深色 / 浅色**主题切换，选择自动记忆（localStorage）

## 运行

### 方式一：直接双击 EXE（无需 Python）

打包好的单文件 `期货行情面板.exe`（约 74 MB），双击即用：

```text
期货行情面板.exe              # 默认 SA2701，端口 8686，自动开浏览器
期货行情面板.exe --port 9000  # 指定端口
期货行情面板.exe --no-browser # 不自动开浏览器
```

- 首次启动会解压到临时目录，约 **5~15 秒**（含启动自检），之后正常；
- 保留控制台窗口，会打印面板地址、天勤状态、行情连通情况，按 `Ctrl+C` 退出；
- **换天勤账号不必重新打包**：把 `tianqin.json` 放在 EXE **同目录**即可覆盖内置账号
  （也可以设 `enabled:false` 停用）；没有外置文件时用内置的出厂账号。

### 方式二：源码运行

```bash
python server.py
```

或直接双击 `启动面板.bat`（仓库里叫 `start-panel.bat`）。启动后自动打开浏览器：

```
http://127.0.0.1:8686/
```

> 源码模式需要 Python 3.8+；**除天勤功能外零第三方依赖**。若要用「天勤」指数档，
> 需 `pip install tqsdk`，并把 `tianqin.json.example` 复制成 `tianqin.json` 填账号。

### 自己重新打包

```bash
打包.bat                 # 仓库里叫 build-exe.bat
# 或手动执行：
python -m PyInstaller --clean --noconfirm 期货行情面板.spec   # 仓库里叫 futures-panel.spec
python -m PyInstaller --clean --noconfirm futures-panel.spec  # ← 在克隆的仓库里用这条
```

产物在 `dist/期货行情面板.exe`。打包要点与踩坑见文末「打包（PyInstaller）说明」。

### 命令行参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--symbol SA2705` | 默认合约 | SA2701 |
| `--port 9000` | 监听端口（被占用自动 +1） | 8686 |
| `--host 0.0.0.0` | 允许局域网访问 | 127.0.0.1 |
| `--no-browser` | 不自动打开浏览器 | - |
| `-v` | 打印访问日志 | - |

### URL 参数（可直接分享定位到某个视图）

```
http://127.0.0.1:8686/?symbol=SA2701&period=day&ind=MACD&theme=dark
```

支持：`symbol` 合约、`product` 品种（切到该品种主力连续）、`period` 周期、
`ind` 副图二指标、`main` 主图指标、`theme` 主题。
URL `product` 优先级高于本地记忆的旧合约。

## 接口说明（数据源）

| 接口 | 用途 |
|---|---|
| `hq.sinajs.cn/list=nf_XXX` | 实时行情快照 |
| `InnerFuturesNewService.getMinLine` | 当日分时 |
| `InnerFuturesNewService.getFewMinLine?type=N` | N 分钟 K 线（上限约 1023 根） |
| `InnerFuturesNewService.getDailyKLine` | 日 K（自该合约上市日起） |

涨跌幅按**昨结算价**计算（与交易所/主流期货软件口径一致）；
分时图基准线按**昨收盘价**绘制（与新浪分时图口径一致）。

## 本地 HTTP 接口

| 路径 | 说明 |
|---|---|
| `/api/quote?symbol=SA2701` | 实时行情（支持主力连续 `SA0`） |
| `/api/products` | 全品种树（79 品种 × 5 交易所，含中文名/停牌标记） |
| `/api/symbols?product=SA` | 同品种合约列表（加权指数置顶 + 主连 + 全部月份） |
| `/api/symbols?product=SA&weight=vol` | 加权口径切换：oi 持仓量（默认）/ vol 成交量 / tianqin 天勤官方 |
| `/api/quote?symbol=SAW` | 加权指数行情（XXW，本地合成） |
| `/api/timeshare?symbol=SAW` | 加权分时（成分合约对齐加权） |
| `/api/kline?symbol=SAW&period=day` | 加权 K 线（1/5/15/30/60/120/day） |
| `/api/tq/status` | 天勤（快期）连接状态 |
| `/api/timeshare?symbol=SA2701` | 分时数据（含完整交易时段 `slots`，供横轴自适应定位） |
| `/api/kline?symbol=SA2701&period=day` | K 线（1/5/15/30/60/120/day） |
| `/api/health` | 健康检查 |

内置 TTL 缓存（交易时段 2~15 秒，休市自动拉长），上游异常时自动回退上一次成功数据。

## 测试

`tests/` 目录自带回归测试（需要本机 Node + jsdom，以及任意 Python 3.8+）：

```bash
# 1. 启动服务后运行前端逻辑验证（148 项断言：全周期渲染 / 分时坐标轴 / 6+5 指标 /
#    SAR 红绿点 / 全品种系统 / 加权指数 / 指数口径切换（仓权·量权·天勤）/
#    K线全量显示与缩放平移 / 底部数据说明折叠与署名 / 中金所时段适配 / DOM 交互）
node tests/test_front.js

# 2. 加权指数全品种校验（72 品种生成/置顶/算法自洽/分时K线/日K全量历史，15 项，需先启动服务）
python tests/verify_weighted.py

# 3. 指数口径分段控件专项校验（渲染/点击/禁用/回落/持久化，16 项，需先启动服务）
node tests/verify_idxseg.js

# 4. 周/月/年K 合成交叉验证（Python 独立实现 vs 前端结果逐根比对）
python tests/verify_synth.py

# 5. 数据源连通性探测
python tests/probe_api.py
```

## 常见问题

- **提示"行情接口异常"**：多为网络问题或系统代理干扰。本程序已自动绕过系统代理直连；
  若公司内网封锁，请检查防火墙。
- **分钟K只有约 1000 根**：新浪接口单次上限约 1023 根，属数据源限制。
  **日K 不受此限**，加权日K 可回溯 7 年（约 2,000 根）。
- **加权日K 第一次打开较慢（数秒到十几秒）**：需要先枚举并拉取数十个月份合约的日K
  再逐根合成，结果有缓存；之后切周期都是瞬时。若觉得慢属正常。
- **休市时数据不动**：正常。休市期间自动降低刷新频率，夜盘 21:00 恢复。
- **改默认品种**：`python server.py --symbol RB2610`（后端接口按品种通用，
  页面右侧列表会自动切换为对应品种的合约）。

## 目录结构

```text
domestic-futures-panel/          # ← 本仓库
├── server.py                    # Python 后端（标准库，零依赖）
├── weighted_index.py            # 加权指数合成 / 天勤（快期）对接
├── app.html                     # ★ 面板前端（单文件，内联 CSS/JS，可离线）
├── index.html                   # GitHub Pages 落地页（非面板本体）
├── usage.html                   # Pages 版《使用说明》
├── datasource.html              # Pages 版《数据源说明》
├── tianqin.json.example         # 天勤账号配置模板（复制为 tianqin.json 后填写）
├── futures-panel.spec           # PyInstaller 打包配置
├── pyinstaller_hooks/           # 补充 hook（补齐 tqsdk 的第三方依赖）
├── build-exe.bat                # 双击打包成 EXE
├── start-panel.bat              # 源码模式双击启动
├── build_site.py                # Markdown → Pages 站点生成器
├── docs/                        # 文档源（Markdown）
│   ├── usage.md
│   └── datasource.md
└── tests/                       # 回归测试
```

> ⚠ **前端文件名**：仓库里面板前端叫 `app.html`（根目录的 `index.html` 让给 GitHub Pages
> 落地页）。`server.py` 的 `panel_html_path()` 对 `index.html` / `app.html` 两个名字都认，
> 克隆仓库后直接 `python server.py` 即可正常工作，无需改名。

---

设计：**公歧子**　微信：**gongqizi0**

## 加权指数算法说明

权重 = 各在交易月份合约的**持仓量**（也可 `weight=vol` 切换为成交量）：

```
指数最新价 = Σ(合约最新价 × 合约持仓量) / Σ(持仓量)
指数昨结   = Σ(合约昨结 × 合约持仓量) / Σ(持仓量)     → 涨跌口径与单合约一致
指数开高低 = 各字段同权重加权
成交量/持仓量 = Σ(各合约)
```

- 主力连续 XX0 **不参与**加权（它只是主力月份的影子，纳入会重复计权）
- 权重明细随接口返回（`components` 字段），加权行 hover 有提示
- 性能：分钟线只取覆盖 97% 权重的前 N 个合约（3~8 个）参与合成，避免为长尾合约发大量请求

### 日K 与分钟线为什么用两套权重口径

这是本项目最容易踩错的地方，**历史日K 必须逐根动态加权**：

| | 分钟线（1/5/…/120分） | 日K（历史长序列） |
|---|---|---|
| 成分合约 | 当刻持仓量 Top-N（3~8 个） | **枚举历史上出现过的全部月份合约** |
| 权重 | 当刻持仓量，**固定不变** | **每根 K 线自身的持仓量**（逐 bar 变化） |
| 理由 | 分钟线只覆盖当日，主力月份不会变 | 主力月份会随时间轮换，用今天的名单去加权历史会**严重漏算** |

> 实测教训：曾用「今天的 Top-N + 固定权重」去合成历史日K，2026-03-16 成交量只有
> 5,452 手，而主力连续同日为 1,156,521 手，**低估约 200 倍**——原因是当天真正的
> 近月合约 SA2605（成交 115 万手）当时不在今天的成分名单里。
> 改为「全合约枚举 + 逐 bar 动态持仓量加权」后，成交量与主力连续量级一致。

另外两个配套细节：

- **枚举深度**：`all_contract_codes(product, years_back=7)` 要回溯 **7 年**才能覆盖
  新浪日K 的实际历史（实测铜可取到 2018-06，加权日K 共 2,014 根）。默认只回溯 3 年时
  会漏掉 2019 / 2022 年的当月合约（如 CU2204 当日成交 6.9 万手），成交量被低估数百倍。
- **`MIN_REAL_COVER = 0.9`**：固定权重模式下，若某根 K 线的「有真实行情成分权重 /
  全体成分权重」低于 0.9，则丢弃该根，避免合约刚上市、多数成分无数据时算出脏值
  （曾出现 1371 而真实值约 1010）。

## 天勤（快期）对接说明

`tianqin.json` 填账号 → `enabled: true` → 重启；前端标题栏选「天勤」档，或直接调
`/api/symbols?product=SA&weight=tianqin`。接入要点（均为实测踩坑）：

| 事项 | 正确做法 |
|---|---|
| 认证参数 | 必须传 `tqsdk.TqAuth(user, pass)` **对象**；传元组/字符串会静默变成 `self._auth is None`，报「请输入 auth 参数」 |
| 指数/主连代码 | `KQ.i@<交易所>.<品种>` = 指数，`KQ.m@<交易所>.<品种>` = 主连 |
| 交易所大小写 | **CZCE / CFFEX 用大写**（`CZCE.SA`、`CFFEX.IF`）；**SHFE / DCE / GFEX / INE 用小写**（`SHFE.rb`、`DCE.m`）。写错报 `non-existent instrument` |
| 返回类型不一 | `KQ.m` 返回 `Quote`，`KQ.i` 返回 `D`（dict 子类），`getattr` 对后者无效 → 统一用 `s[字段名]` 取值 |
| 字段名 | 开高低是 `open` / `highest` / `lowest`（**没有** `open_price`） |
| 首次查询超时 | `TqApi` 构造后数据通道未就绪，先预热一次 `get_quote("SHFE.rb2601")` 即可稳定 |
| 抑制日志 | `TqApi(auth=..., web_gui=False, disable_print=True)` |
| **NaN 陷阱** | 非交易时段 `bid_price1`/`ask_price1` 常返回 `nan`，`json.dumps` 会写出**裸 `NaN`（非法 JSON）**，浏览器 `res.json()` 直接抛错 → 源头收敛 + 响应层 `allow_nan=False` 双保险 |

交叉验证结果（本地持仓量加权 vs 天勤官方 `KQ.i`，同一次采样）：

| 品种 | 本地加权 | 天勤官方 | 偏差 |
|---|---|---|---|
| SA 纯碱 | 1008.87 | 1009.0 | +0.013% |
| RB 螺纹钢 | 3096.69 | 3097.0 | +0.010% |
| M 豆粕 | 3311.87 | 3312.0 | +0.004% |
| IF 沪深300 | 4243.59 | 4243.3 | −0.007% |
| LC 碳酸锂 | 116501.76 | 116549.0 | +0.041% |
| CU 铜 | 110069.64 | 110072.0 | +0.002% |

## 打包（PyInstaller）说明

单文件 EXE（`console=True`，保留控制台便于排错），实测 **74 MB**，启动约 5~15 秒。
下面 5 个坑都是打包过程中真实踩到并修复的，改 spec 前建议先读一遍。

### 1. 资源路径：`__file__` 在打包后指向临时目录

单文件模式会把资源解压到临时目录，`__file__` 随之改变。源码里用
`dirname(__file__)` 找 `index.html`，打包后会 404。因此区分两个目录：

| 变量 | 含义 | 源码模式 | 打包模式 |
|---|---|---|---|
| `BUNDLE_DIR` / `APP_DIR` | 只读资源（index.html） | 脚本目录 | `sys._MEIPASS` |
| `EXE_DIR` | 用户可改文件（tianqin.json） | 脚本目录 | **exe 实际所在目录** |

### 2. 绝不排除 `numpy` / `pandas`

`tqsdk/api.py` 第 39/44 行是**无保护**的顶层导入：

```python
import numpy as np
import pandas as pd
from pandas._libs.internals import BlockPlacement
```

曾把 numpy/pandas 放进 `excludes` 想瘦身 → 打包后 `import tqsdk` 直接失败，
`/api/tq/status` 恒为 `installed:false`，**"天勤"档整档不可用**。
代价就是体积从 22 MB 涨到 74 MB——这是接入天勤必须付的成本。

### 3. 绝不排除 `unittest`

tqsdk 自己不 import unittest，但依赖链会走到
`numpy.testing._private.utils`，那里是**顶层** `import unittest`。
排除后报 `ModuleNotFoundError: No module named 'unittest'`。标准库不占体积，不值得冒险。

### 4. tqsdk 是惰性导入 → 必须配 hook

本项目在函数体内 `import tqsdk`，PyInstaller 静态分析扫不到这条链，
`tqsdk/api.py` 自己的依赖（`sgqlc`、`shinny_structlog` 等）不会被收集。
tqsdk 自带 hook 只负责 datas，因此补了 `pyinstaller_hooks/hook-tqsdk.py`
显式声明这些 hiddenimports，并在 spec 里 `hookspath=[HOOK_DIR]`。

### 5. 验证 EXE 是否真的可用的方法

不要只看"打包成功"，要直接查归档内容 + 跑接口：

```python
# 查 CArchive（二进制/数据文件）
from PyInstaller.archive.readers import CArchiveReader
a = CArchiveReader('dist/期货行情面板.exe'); print(len(a.toc))

# 查 PYZ（纯 Python 模块，sgqlc 这类在这里而不在 CArchive）
from PyInstaller.archive.readers import ZlibArchiveReader
# 先用 CArchiveReader.extract('PYZ.pyz') 导出再读

# 最终以接口为准
curl -s http://127.0.0.1:8686/api/tq/status   # installed 必须为 true
```

调试期建议让 `tq_status()` 返回 `importError` 字段——否则
`except Exception: pass` 会把真实原因吞掉，只看到 `installed:false` 无从下手。

### 6. 端口探测：Windows 上不能带 `SO_REUSEADDR`

`pick_port()` 原先设了 `SO_REUSEADDR` 再探测。**Windows 的语义与 Linux 不同**：
它允许两个 socket 绑定完全相同的 `(addr, port)`，于是"探测可用"永远为真，
两个进程会同时 LISTEN 在同一端口 —— 表现为"改了代码重启却没生效、数据是旧的"。
（本机确实出现过两个监听进程，排查了很久。）

修法：探测用**不带** `SO_REUSEADDR` 的裸 bind；服务端用自定义
`PanelHTTPServer` 把 `allow_reuse_address` 设为 `False`，端口被占直接报错退出。

### 7. 单文件模式的启动慢是正常的

每次启动都要把 ~74 MB 解压到 `%TEMP%\_MEIxxxxxx`，首次约 5~15 秒。
启动自检（拉一次行情 + 合约列表）又要几秒，所以"双击后要等十几秒"是正常现象。

### 8. EXE 实测验证结果

| 项目 | 结果 |
|---|---|
| 文件大小 | 74 MB（单文件） |
| 启动到可访问 | 约 12~24 秒 |
| tqsdk | `installed=true version=3.10.2` |
| 天勤档实连 | 成功，官方纯碱指数 1009.0（与本地加权偏差 <0.05%） |
| 全品种 | 79 品种 / 5 交易所 |
| 加权日K | 1,656~2,014 根（回溯至 2018-06） |
| 外置 tianqin.json 覆盖 | 生效（`configExternal=true`） |
| `test_front.js` | **148 / 148** |
| `verify_idxseg.js` | **16 / 16** |
| `verify_weighted.py` | **15 / 15** |

> 上述三套测试均以 `BASE=http://127.0.0.1:<EXE端口>` 指向 EXE 实例运行，
> 即打包产物与源码模式功能等价。

