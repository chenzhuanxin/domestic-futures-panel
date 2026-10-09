/* 前端逻辑验证：jsdom + Canvas 打桩 + 真实本地服务 */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const BASE = process.env.BASE || 'http://127.0.0.1:8686';
const HTML = path.join(__dirname, '..', 'index.html');
const OUT = __dirname;

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e && (e.stack || e.message || e))));
vc.on('error', (...a) => errors.push('console.error: ' + a.map(String).join(' ')));
if (process.env.DBG) vc.on('log', (...a) => console.log('    [page] ' + a.map(String).join(' ')));

const stats = { fillRect: 0, fillText: 0, stroke: 0, lineTo: 0 };

function makeCtx() {
  const noop = () => {};
  const c = {
    canvas: null,
    save: noop, restore: noop, beginPath: noop, closePath: noop,
    moveTo: noop, stroke: noop, fill: noop, rect: noop, arc: noop,
    clearRect: noop, strokeRect: noop, setTransform: noop, scale: noop,
    translate: noop, rotate: noop, setLineDash: noop, clip: noop,
    resetTransform: noop, drawImage: noop, quadraticCurveTo: noop,
    bezierCurveTo: noop, ellipse: noop, roundRect: noop, isPointInPath: () => false,
    lineTo: () => { stats.lineTo++; },
    fillRect: () => { stats.fillRect++; },
    fillText: () => { stats.fillText++; },
    measureText: t => ({ width: String(t).length * 6, actualBoundingBoxAscent: 8 }),
    createLinearGradient: () => ({ addColorStop: noop }),
    createRadialGradient: () => ({ addColorStop: noop }),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '',
    textBaseline: '', globalAlpha: 1, lineJoin: '', lineCap: '', globalCompositeOperation: '',
  };
  c.stroke = () => { stats.stroke++; };
  return c;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// 分时纵轴的"整档百分比"候选（与前端 PCT_STEPS 一致，用于交叉核对）
const PCT_LIST = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15, 20];
process.on('uncaughtException', e => {
  errors.push('uncaughtException: ' + (e && (e.stack || e.message || e)));
  console.log('  [!!] 未捕获异常: ' + (e && e.message));
});

const results = [];
function check(name, cond, extra) {
  results.push({ name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
  console.log((cond ? '  [PASS] ' : '  [FAIL] ') + name + (extra !== undefined ? '  → ' + extra : ''));
}

(async () => {
  const dom = new JSDOM(fs.readFileSync(HTML, 'utf8'), {
    url: BASE + '/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(win) {
      win.fetch = (url, opt) => {
        const u = String(url).startsWith('http') ? String(url) : BASE + String(url);
        return fetch(u, opt);
      };
      win.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
      win.HTMLCanvasElement.prototype.getContext = function () {
        if (!this.__ctx) { this.__ctx = makeCtx(); this.__ctx.canvas = this; }
        return this.__ctx;
      };
      win.Element.prototype.getBoundingClientRect = function () {
        return { x: 0, y: 0, left: 0, top: 0, right: 1200, bottom: 700, width: 1200, height: 700 };
      };
      win.devicePixelRatio = 1;
    },
  });

  const win = dom.window;
  const doc = win.document;

  console.log('\n========== 1. 启动与数据加载 ==========');
  let waited = 0;
  // 注意：refreshAll 内 loadQuote / loadSymbols / loadChart 三路并行，loadChart(timeshare)
  // 比前两路慢，因此"quote 与 symbols 都有了"并不代表分时已就绪。若此处的就绪判据只要求
  // quote+symbols，150ms 轮询可能恰好落在分时返回前的空窗，产生偶发假失败（实测出现过）。
  // 第一屏默认周期就是分时，所以直接等分时点到位，把竞态窗口关掉。
  const ready = () => {
    if (!win.App) return false;
    const s = win.App.state;
    if (!s.quote || !s.symbols || !s.symbols.count) return false;
    if (s.period === 'timeshare') {
      return !!(s.timeshare && s.timeshare.points && s.timeshare.points.length);
    }
    return !!s.bars.length;
  };
  while (!ready() && waited < 30000) { await sleep(150); waited += 150; }
  check('window.App 已挂载（脚本无致命错误）', !!win.App);
  check('实时行情已加载', !!(win.App && win.App.state.quote), win.App && win.App.state.quote && (win.App.state.quote.name + ' ' + win.App.state.quote.last));
  check('合约列表已加载', !!(win.App && win.App.state.symbols), win.App && win.App.state.symbols && (win.App.state.symbols.count + ' 个'));
  check('默认周期数据已加载', !!(win.App && win.App.state.timeshare && win.App.state.timeshare.points.length), win.App && win.App.state.timeshare && win.App.state.timeshare.points.length + ' 个分时点');
  check('分时模式也生成合成分钟K（供副图二指标使用）',
    !!(win.App && win.App.state.bars.length), win.App && win.App.state.bars.length + ' 根');

  const App = win.App;
  const daily = await (await fetch(BASE + '/api/kline?symbol=SA2701&period=day')).json();
  fs.writeFileSync(path.join(OUT, 'daily.json'), JSON.stringify(daily.data.bars));

  console.log('\n========== 2. 全周期渲染 ==========');
  const periods = ['timeshare', '1', '5', '15', '30', '60', '120', 'day', 'week', 'month', 'year'];
  for (const p of periods) {
    const before = { ...stats };
    try {
      await App.loadChart(p);
      const n = p === 'timeshare' ? App.state.timeshare.points.length : App.state.bars.length;
      const painted = stats.fillRect > before.fillRect || stats.lineTo > before.lineTo || stats.fillText > before.fillText;
      check('周期 ' + p + ' 渲染', n > 0 && painted, n + ' 根, 绘制调用 +' + ((stats.fillRect - before.fillRect) + (stats.lineTo - before.lineTo)) );
    } catch (e) {
      check('周期 ' + p + ' 渲染', false, 'EX: ' + (e.stack || e.message));
    }
  }

  console.log('\n========== 2b. 分时横纵轴自适应 ==========');
  await App.loadChart('timeshare');
  const tsRaw = await (await fetch(BASE + '/api/timeshare?symbol=SA2701')).json();
  const rawSlots = tsRaw.data.slots || [];
  check('接口返回完整交易时段', rawSlots.length >= 300, rawSlots.length + ' 个分钟槽');
  check('时段按交易日内顺序排列（夜盘在日盘之前）',
    App.minuteKey('21:00') < App.minuteKey('09:00')
    && App.minuteKey('09:00') < App.minuteKey('13:30')
    && App.minuteKey('13:30') < App.minuteKey('15:00'),
    ['21:00', '09:00', '13:30', '15:00'].map(App.minuteKey).join(' < '));

  const ax = App.tsAxisData();
  const pts = App.state.timeshare.points;
  check('坐标轴时段数 = 完整时段', ax.slots.length >= 300, ax.slots.length + ' 槽 / ' + pts.length + ' 点');
  check('每个成交点都落在时段轴上', pts.every(p => ax.slots.indexOf(p.t) >= 0),
    '首点槽位=' + ax.slotOf[0] + ' 末点槽位=' + ax.slotOf[ax.slotOf.length - 1]);
  check('槽位严格递增（曲线不会折返）',
    ax.slotOf.every((v, i) => i === 0 || v > ax.slotOf[i - 1]), ax.slotOf.slice(0, 5).join(',') + ' …');
  check('横轴不再被少数几个点拉伸铺满',
    ax.slotOf[ax.slotOf.length - 1] === ax.slots.indexOf(pts[pts.length - 1].t)
    && ax.slots.indexOf(pts[pts.length - 1].t) < ax.slots.length,
    '末点位于 ' + (ax.slotOf[ax.slotOf.length - 1] + 1) + '/' + ax.slots.length + ' 格');
  check('小节分界已识别（夜盘/上午/下午）', ax.bounds.length >= 2, '分界索引 ' + ax.bounds.join(','));

  // 纵轴：无论行情大小，价格必须全部落在轴内且上下对称、百分比为整档
  const cases = [
    [1010, 1012, 1009], [1010, 1046, 1002], [1010, 1010.4, 1009.6], [1010, 1080, 900],
    [2200, 2200, 2200], [780.5, 795, 770],
  ];
  let rangeOk = true, rangeMsg = '';
  for (const [pre, hi, lo] of cases) {
    const r = App.niceTimeshareRange(pre, hi, lo);
    const contain = r.top >= hi - 1e-9 && r.bot <= lo + 1e-9;
    const sym = Math.abs((r.top - pre) - (pre - r.bot)) < 1e-6;
    const pctOk = r.top > pre && PCT_LIST.indexOf(+r.pct.toFixed(6)) >= 0;
    if (!(contain && sym && pctOk) && rangeOk) {
      rangeOk = false;
      rangeMsg = 'pre=' + pre + ' hi=' + hi + ' lo=' + lo
        + ' → ' + r.bot.toFixed(2) + '~' + r.top.toFixed(2) + ' (' + r.pct + '%)';
    }
  }
  check('纵轴自适应：覆盖全部价格 + 上下对称 + 百分比为整档', rangeOk,
    rangeOk ? cases.length + ' 组行情全部通过' : rangeMsg);

  // 十字光标：鼠标落在已走过的区域时吸附到最近的真实成交点
  App.state.hover = { x: 100, y: 200, idx: null, zone: null, inside: true };
  App.draw();
  const hIdx = App.state.hover.idx;
  check('十字光标吸附到最近成交点', Number.isInteger(hIdx) && hIdx >= 0 && hIdx < pts.length,
    'idx=' + hIdx + ' / ' + pts.length + ' 点');
  // 鼠标右移时吸附点必须单调不减；移到最右侧（数据尽头之外）必须钳到末点
  App.state.hover = { x: 99999, y: 200, idx: null, zone: null, inside: true };
  App.draw();
  const hIdxEnd = App.state.hover.idx;
  check('光标吸附不会超出数据范围', hIdxEnd === pts.length - 1,
    '最右 → idx=' + hIdxEnd + '（末点 ' + (pts.length - 1) + '）');
  App.state.hover = { x: -99999, y: 200, idx: null, zone: null, inside: true };
  App.draw();
  check('光标吸附不会落到数据之前', App.state.hover.idx === 0, '最左 → idx=' + App.state.hover.idx);
  App.state.hover = null;
  App.draw();

  console.log('\n========== 3. 全部副图指标渲染 ==========');

  await App.loadChart('day');
  for (const ind of ['MACD', 'KDJ', 'RSI', 'BOLL', 'WR', 'DMI']) {
    App.state.ind = ind;
    const before = { ...stats };
    try {
      App.draw();
      check('副图二 ' + ind, stats.lineTo > before.lineTo || stats.fillRect > before.fillRect,
        'lineTo+' + (stats.lineTo - before.lineTo) + ' fillRect+' + (stats.fillRect - before.fillRect));
    } catch (e) {
      check('副图二 ' + ind, false, 'EX: ' + (e.stack || e.message));
    }
  }

  console.log('\n========== 3b. 主图叠加指标渲染（MA/SAR/BOLL/EXPMA/BBIBOLL） ==========');
  await App.loadChart('day');
  for (const m of ['MA', 'SAR', 'BOLL', 'EXPMA', 'BBIBOLL']) {
    App.state.mainInd = m;
    const before = { ...stats };
    try {
      App.draw();
      const drew = stats.lineTo > before.lineTo || stats.fillRect > before.fillRect;
      check('主图指标 ' + m, drew,
        'lineTo+' + (stats.lineTo - before.lineTo) + ' fillRect+' + (stats.fillRect - before.fillRect));
    } catch (e) {
      check('主图指标 ' + m, false, 'EX: ' + (e.stack || e.message));
    }
  }
  App.state.mainInd = 'MA';

  console.log('\n========== 4. 指标数值合理性 ==========');
  const bars = App.state.bars;
  const closes = bars.map(b => b.c);
  const last = closes.length - 1;
  const ma5 = App.TA.sma(closes, 5);
  const manual5 = closes.slice(-5).reduce((a, b) => a + b, 0) / 5;
  check('SMA5 手工核对', Math.abs(ma5[last] - manual5) < 1e-6, ma5[last].toFixed(4) + ' vs ' + manual5.toFixed(4));
  const macd = App.TA.macd(closes);
  check('MACD 数值有效', isFinite(macd.dif[last]) && isFinite(macd.dea[last]) && isFinite(macd.bar[last]),
    'DIF=' + macd.dif[last].toFixed(3) + ' DEA=' + macd.dea[last].toFixed(3) + ' MACD=' + macd.bar[last].toFixed(3));
  const kdj = App.TA.kdj(bars);
  check('KDJ 在合理区间', kdj.K[last] > -50 && kdj.K[last] < 150, 'K=' + kdj.K[last].toFixed(2) + ' D=' + kdj.D[last].toFixed(2) + ' J=' + kdj.J[last].toFixed(2));
  const rsi = App.TA.rsi(closes, 6);
  check('RSI6 在 0~100', rsi[last] >= 0 && rsi[last] <= 100, rsi[last].toFixed(2));
  const boll = App.TA.boll(closes, 20, 2);
  check('BOLL 上轨>中轨>下轨', boll.up[last] > boll.mid[last] && boll.mid[last] > boll.dn[last],
    boll.up[last].toFixed(1) + ' / ' + boll.mid[last].toFixed(1) + ' / ' + boll.dn[last].toFixed(1));
  const wr = App.TA.wr(bars, 14);
  check('WR 在 0~100', wr[last] >= 0 && wr[last] <= 100, wr[last].toFixed(2));
  const dmi = App.TA.dmi(bars, 14, 6);
  check('DMI 数值有效', dmi.pdi[last] > 0 && dmi.mdi[last] > 0 && dmi.adx[last] > 0,
    '+DI=' + dmi.pdi[last].toFixed(2) + ' -DI=' + dmi.mdi[last].toFixed(2) + ' ADX=' + dmi.adx[last].toFixed(2));

  // RSI 边界：单调上涨应接近 100
  const rising = Array.from({ length: 60 }, (_, i) => 100 + i);
  const rsiUp = App.TA.rsi(rising, 6);
  check('RSI 单调上涨趋近 100', rsiUp[59] > 99, rsiUp[59].toFixed(2));

  // 新增主图指标
  const sarRes = App.TA.sar(bars);
  check('SAR 返回点值 + 多空方向两组数据',
    Array.isArray(sarRes.values) && Array.isArray(sarRes.trend)
    && sarRes.values.length === bars.length && sarRes.trend.length === bars.length,
    'values=' + sarRes.values.length + ' trend=' + sarRes.trend.length);
  const sarV = sarRes.values;
  const sarTail = sarV.slice(-30).filter(v => v !== null && isFinite(v));
  check('SAR 数值有效且贴近价格', sarTail.length > 25 && sarTail.every(v => v > 0),
    '样本' + sarTail.length + ' 末值=' + sarV[sarV.length - 1].toFixed(2));

  // SAR 红绿点：多头时 SAR 必在 K 线下方，空头时必在上方（与国内软件口径一致）
  let sarBullOk = true, sarBearOk = true, sarBullN = 0, sarBearN = 0, sarBad = '';
  for (let i = 2; i < bars.length; i++) {
    const v = sarRes.values[i], t = sarRes.trend[i];
    if (v === null || t === null) continue;
    if (t) {                                     // 多头 → 红点，应在最低价下方
      sarBullN++;
      if (!(v <= bars[i].l + 1e-9)) { sarBullOk = false; sarBad ||= '第' + i + '根 多头SAR' + v + ' 高于最低' + bars[i].l; }
    } else {                                     // 空头 → 绿点，应在最高价上方
      sarBearN++;
      if (!(v >= bars[i].h - 1e-9)) { sarBearOk = false; sarBad ||= '第' + i + '根 空头SAR' + v + ' 低于最高' + bars[i].h; }
    }
  }
  check('SAR 多头点（红）位于 K 线下方', sarBullOk && sarBullN > 0, sarBullN + ' 个多头点' + (sarBullOk ? '' : ' → ' + sarBad));
  check('SAR 空头点（绿）位于 K 线上方', sarBearOk && sarBearN > 0, sarBearN + ' 个空头点');
  check('SAR 多空两种状态都出现过（红绿双色可见）', sarBullN > 0 && sarBearN > 0,
    '多头 ' + sarBullN + ' / 空头 ' + sarBearN);

  const bbi = App.TA.bbiboll(closes, 11, 3);
  check('BBIBOLL 上轨>BBI>下轨', bbi.up[last] > bbi.bbi[last] && bbi.bbi[last] > bbi.dn[last],
    bbi.up[last].toFixed(1) + ' / ' + bbi.bbi[last].toFixed(1) + ' / ' + bbi.dn[last].toFixed(1));
  const ex5 = App.TA.ema(closes, 5), ex60 = App.TA.ema(closes, 60);
  check('EXPMA 有效（EMA5 比 EMA60 更贴近价格）',
    Math.abs(ex5[last] - closes[last]) < Math.abs(ex60[last] - closes[last]),
    'EXPMA5=' + ex5[last].toFixed(2) + ' EXPMA60=' + ex60[last].toFixed(2) + ' 收盘=' + closes[last].toFixed(2));

  console.log('\n========== 5. 周/月/年 K 合成（导出给 Python 对照） ==========');
  const dayBars = (await (await fetch(BASE + '/api/kline?symbol=SA2701&period=day')).json()).data.bars;
  for (const p of ['week', 'month', 'year']) {
    const out = App.synth(dayBars, p);
    fs.writeFileSync(path.join(OUT, 'front_' + p + '.json'), JSON.stringify(out));
    check('合成 ' + p, out.length > 0, out.length + ' 根');
  }
  fs.writeFileSync(path.join(OUT, 'daily_raw.json'), JSON.stringify(dayBars));

  console.log('\n========== 6. 全品种系统（跨交易所） ==========');
  {
    const raw = await (await fetch(BASE + '/api/products')).json();
    const pt = raw.data;
    check('全品种树接口返回', pt.count > 60, pt.count + ' 个品种');
    check('覆盖四家交易所 + 广期所', pt.groups.length >= 5,
      pt.groups.map(g => g.exchange + '(' + g.count + ')').join(' '));
    check('中金所品种已收录且命名正确',
      pt.groups.some(g => g.exchange === '中金所' && g.items.some(i => i.product === 'IF' && i.name === '沪深300')),
      pt.groups.find(g => g.exchange === '中金所') ? pt.groups.find(g => g.exchange === '中金所').items.map(i => i.product + '=' + i.name).join(' ') : '无');
    const all = pt.groups.flatMap(g => g.items);
    check('已停牌品种被标记（不混入在交易列表）', all.some(i => !i.tradeable),
      '停牌: ' + all.filter(i => !i.tradeable).map(i => i.product).join(' '));
    check('在交易品种数量合理', all.filter(i => i.tradeable).length > 60,
      all.filter(i => i.tradeable).length + ' 个在交易');

    // 品种列表 DOM
    check('品种列表已渲染', doc.querySelectorAll('.prod').length > 0,
      doc.querySelectorAll('.prod').length + ' 行');
    check('品种按交易所分组显示', doc.querySelectorAll('.exch').length >= 5,
      doc.querySelectorAll('.exch').length + ' 组');
    check('当前品种在列表中被高亮',
      !!doc.querySelector('.prod.sel') && doc.querySelector('.prod.sel').dataset.product === App.getProduct(),
      doc.querySelector('.prod.sel') ? doc.querySelector('.prod.sel').dataset.product : '无');

    // 搜索
    const search = doc.getElementById('prodSearch');
    search.value = '碳酸锂';
    search.dispatchEvent(new win.Event('input'));
    check('按中文名搜索品种', doc.querySelectorAll('.prod').length === 1
      && doc.querySelector('.prod').dataset.product === 'LC',
      doc.querySelectorAll('.prod').length + ' 行 → ' + (doc.querySelector('.prod') ? doc.querySelector('.prod').dataset.product : ''));
    search.value = 'IF';
    search.dispatchEvent(new win.Event('input'));
    check('按代码搜索品种', doc.querySelectorAll('.prod').length === 1
      && doc.querySelector('.prod').dataset.product === 'IF',
      doc.querySelectorAll('.prod').length + ' 行');
    search.value = 'zzzz不存在';
    search.dispatchEvent(new win.Event('input'));
    check('搜索无结果时给出提示', doc.querySelectorAll('.prod').length === 0
      && doc.getElementById('prodList').textContent.includes('没有匹配'),
      doc.getElementById('prodList').textContent.trim().slice(0, 20));
    search.value = '';
    search.dispatchEvent(new win.Event('input'));

    // 切换到中金所品种（字段布局与商品期货不同）
    await App.switchProduct('IF');
    let waited2 = 0;
    while (!(App.state.quote && App.state.quote.code === 'IF0' && App.state.symbols) && waited2 < 40000) {
      await sleep(200); waited2 += 200;
    }
    check('切换到中金所品种：行情已加载', !!App.state.quote, App.state.quote && (App.state.quote.code + ' ' + App.state.quote.last));
    check('中金所主力合约代码为 IF0', App.state.quote && App.state.quote.code === 'IF0', App.state.quote && App.state.quote.code);
    check('中金所行情交易所标为「中金所」', App.state.quote && App.state.quote.exchange === '中金所', App.state.quote && App.state.quote.exchange);
    // 显式切到分时视图，验证中金所时段自动适配（无夜盘、09:30 开盘）
    await App.loadChart('timeshare');
    let waited2b = 0;
    while (!(App.state.timeshare && App.state.timeshare.points.length) && waited2b < 30000) {
      await sleep(200); waited2b += 200;
    }
    const ifPts = (App.state.timeshare && App.state.timeshare.points) || [];
    check('中金所分时已加载（09:30 起）', ifPts.length > 0 && ifPts[0].t === '09:30',
      ifPts.length + ' 点，首点 ' + (ifPts[0] ? ifPts[0].t : '无'));
    check('中金所交易时段自动适配（无 21:00 夜盘）',
      ifPts.length > 0 && !ifPts.some(p => p.t >= '20:00' || p.t < '09:00'),
      ifPts.length ? '首 ' + ifPts[0].t + ' 末 ' + ifPts[ifPts.length - 1].t : '无');
    check('中金所分时时段轴同步适配（无夜盘槽位）', (() => {
      const a = App.tsAxisData();
      return a.slots.length < 300 && a.slots[0] >= '09:30';
    })(), (() => { const a = App.tsAxisData(); return a.slots.length + ' 槽，首槽 ' + a.slots[0]; })());
    check('中金所合约列表已加载', !!(App.state.symbols && App.state.symbols.count),
      App.state.symbols && App.state.symbols.count + ' 个');
    // 切回纯碱，保证后续断言在熟悉的数据上
    await App.switchProduct('SA');
    let waited3 = 0;
    while (!(App.state.quote && App.state.quote.code.indexOf('SA') === 0
             && App.state.symbols && App.state.symbols.product === 'SA'
             && App.state.symbols.count >= 13) && waited3 < 40000) {
      await sleep(200); waited3 += 200;
    }
    check('切回纯碱品种成功', App.state.quote && App.state.quote.code.indexOf('SA') === 0,
      App.state.quote && App.state.quote.code);
    check('切回后合约列表回到纯碱', App.state.symbols && App.state.symbols.product === 'SA',
      App.state.symbols && App.state.symbols.product);
    await App.loadChart('day');
    let waited3b = 0;
    while (!App.state.bars.length && waited3b < 30000) { await sleep(200); waited3b += 200; }
    check('切回后日K已重新加载', App.state.bars.length > 0, App.state.bars.length + ' 根');
  }

  console.log('\n========== 6b. 加权指数（持仓量加权，置顶） ==========');
  {
    const sx = App.state.symbols;
    const w = sx && sx.items.find(it => it.isWeighted);
    check('合约列表含加权指数行', !!w, w ? w.code + ' ' + w.name : '无');
    check('加权指数排在列表第一位', sx && sx.items[0].isWeighted,
      sx && sx.items[0].code);
    check('加权指数被标记为合成品种', !!(w && w.isWeighted && !w.isMain), 
      w ? 'isWeighted=' + w.isWeighted + ' isMain=' + w.isMain : '无');
    // 独立复算：Σ(持仓×价)/Σ持仓 —— 用 components 自洽验证（避免另发请求时行情跳动）
    if (w && w.components && w.components.length >= 2) {
      const recon = w.components.reduce((a, c) => a + c.weight * c.last, 0);
      const wsum = w.components.reduce((a, c) => a + c.weight, 0);
      const tol = Math.max(0.05, Math.abs(w.last) * 1e-5);
      check('加权价 = Σ(权重×成分最新价)', Math.abs(recon - w.last) <= tol,
        '反推 ' + recon.toFixed(2) + ' vs 值 ' + w.last.toFixed(2));
      check('成分权重之和 = 1', Math.abs(wsum - 1) <= 0.01, wsum.toFixed(6));
      check('成分合约数 ≥ 2', w.components.length >= 2, w.components.length + ' 个');
      check('加权价落在成分价格区间内', (() => {
        const ps = w.components.map(c => c.last);
        return w.last >= Math.min(...ps) - 0.01 && w.last <= Math.max(...ps) + 0.01;
      })(), '[' + Math.min(...w.components.map(c => c.last)).toFixed(1) + ','
           + Math.max(...w.components.map(c => c.last)).toFixed(1) + '] → ' + w.last.toFixed(2));
    }
    // 加权行在 DOM 中有独立样式与 Σ 标记
    const row = doc.querySelector('.sym.weighted');
    check('加权行 DOM 已渲染且带标记', !!row && !!row.querySelector('.tag.wt'),
      row ? row.className + ' tag=' + (row.querySelector('.tag.wt') || {}).textContent : '无');
    // 切换到加权指数：行情/分时/K线都要能取到
    await App.switchToSymbol(w.code);
    let ww = 0;
    while (!(App.state.quote && App.state.quote.code === w.code && App.state.bars.length) && ww < 40000) {
      await sleep(200); ww += 200;
    }
    check('切换到加权指数：行情已加载', App.state.quote && App.state.quote.code === w.code,
      App.state.quote && (App.state.quote.code + ' ' + App.state.quote.last));
    check('加权指数日K已加载', App.state.bars.length > 0, App.state.bars.length + ' 根');
    await App.loadChart('timeshare');
    let wt = 0;
    while (!(App.state.timeshare && App.state.timeshare.points.length) && wt < 40000) {
      await sleep(200); wt += 200;
    }
    check('加权指数分时已加载', !!(App.state.timeshare && App.state.timeshare.points.length),
      App.state.timeshare ? App.state.timeshare.points.length + ' 点' : '无');
    check('加权分时时段轴带完整 slots', (() => {
      const a = App.tsAxisData();
      return a.slots.length >= 300;
    })(), (() => App.tsAxisData().slots.length + ' 槽')());
    // 切回主力连续，保证后续断言在熟悉的数据上
    await App.switchToSymbol('SA0');
    let wb = 0;
    while (!(App.state.quote && App.state.quote.code === 'SA0') && wb < 30000) {
      await sleep(200); wb += 200;
    }
    await App.loadChart('day');
    let wb2 = 0;
    while (!App.state.bars.length && wb2 < 30000) { await sleep(200); wb2 += 200; }
    check('切回主力连续成功', App.state.quote && App.state.quote.code === 'SA0',
      App.state.quote && App.state.quote.code);
  }

  console.log('\n========== 6c. 指数口径切换（仓权 / 量权 / 天勤） ==========');
  {
    // 分段控件存在且三档齐全
    const seg = doc.getElementById('idxSeg');
    const btns = seg ? [...seg.querySelectorAll('button')] : [];
    check('指数口径分段控件存在', !!seg && btns.length === 3,
      btns.map(b => b.dataset.wm + (b.disabled ? '(禁用)' : '')).join(' '));

    // 1) 成交量加权：weightMode 与加权行标签都要跟着变
    await App.setWeightMode('vol');
    let v1 = 0;
    while (!(App.state.symbols && App.state.symbols.weightMode === 'vol') && v1 < 30000) {
      await sleep(200); v1 += 200;
    }
    const vw = App.state.symbols && App.state.symbols.items.find(it => it.isWeighted);
    check('量权模式回传 weightMode=vol',
      App.state.symbols && App.state.symbols.weightMode === 'vol',
      App.state.symbols && App.state.symbols.weightMode);
    check('量权模式加权行仍置顶', App.state.symbols && App.state.symbols.items[0].isWeighted,
      App.state.symbols && App.state.symbols.items[0].code);

    // 2) 天勤官方指数：仅在账号配置可用时才断言
    const tqOk = !!App.state.tqOk;
    check('天勤可用性已探测', typeof App.state.tqOk === 'boolean',
      'tqOk=' + App.state.tqOk + ' err=' + (App.state.tqErr || '-'));
    const dbgRet = await App.setWeightMode('tianqin');
    let v2 = 0;
    while (!(App.state.symbols && App.state.symbols.weightMode === 'tianqin') && v2 < 60000) {
      await sleep(250); v2 += 250;
    }
    const tw = App.state.symbols && App.state.symbols.items.find(it => it.isWeighted);
    check('天勤模式回传 weightMode=tianqin',
      App.state.symbols && App.state.symbols.weightMode === 'tianqin',
      App.state.symbols && App.state.symbols.weightMode);
    if (tqOk) {
      check('天勤指数行来源为 tianqin', !!(tw && tw.source === 'tianqin'),
        tw ? 'src=' + tw.source + ' ' + tw.name + ' ' + tw.last : '无');
      check('天勤指数行置顶且带天勤标记', !!(App.state.symbols && App.state.symbols.items[0].isWeighted),
        App.state.symbols && App.state.symbols.items[0].code);
      const tag = doc.querySelector('.sym.weighted .tag.wt');
      check('天勤加权行 DOM 标记为「天勤」', !!tag && tag.textContent.indexOf('天勤') >= 0,
        tag ? tag.textContent : '无');
      // 天勤主连行（XX0，名称含"天勤"）
      const tqm = App.state.symbols.items.find(it => it.isMain && it.source === 'tianqin');
      check('天勤主连行已并入列表', !!tqm, tqm ? tqm.code + ' ' + tqm.name + ' ' + tqm.last : '无');
    } else {
      check('天勤未配置时按钮禁用（不误报）', (() => {
        const b = btns.find(x => x.dataset.wm === 'tianqin');
        return !!b && b.disabled;
      })(), 'tqOk=false');
    }

    // 3) 回到默认仓权，保证后续段落在熟悉状态
    await App.setWeightMode('oi');
    let v3 = 0;
    while (!(App.state.symbols && App.state.symbols.weightMode === 'oi') && v3 < 30000) {
      await sleep(200); v3 += 200;
    }
    check('切回仓权模式生效',
      App.state.symbols && App.state.symbols.weightMode === 'oi',
      App.state.symbols && App.state.symbols.weightMode);
  }

  console.log('\n========== 7. DOM 与交互 ==========');
  check('侧栏合约条目数 = ' + App.state.symbols.count, doc.querySelectorAll('.sym').length === App.state.symbols.count, doc.querySelectorAll('.sym').length + ' 条');
  check('主力合约有「主」标签', !!doc.querySelector('.sym .tag'), doc.querySelector('.sym .tag') ? '存在' : '缺失');
  check('顶部最新价已填充', /^\d+\.\d+$/.test(doc.getElementById('hLast').textContent), doc.getElementById('hLast').textContent);
  check('顶部涨跌色正确（涨=up）', App.state.quote.change > 0 ? doc.getElementById('hLast').classList.contains('up') : true,
    'change=' + App.state.quote.change + ' class=' + doc.getElementById('hLast').className);
  check('报价条名称', doc.getElementById('hName').textContent === App.state.quote.name, doc.getElementById('hName').textContent);

  // 顶部 12 项明细
  const statIds = ['sLast', 'sOpen', 'sHigh', 'sLow', 'sSettle', 'sPre',
                   'sOI', 'sVol', 'sBid', 'sAsk', 'sBidVol', 'sAskVol'];
  const filled = statIds.filter(id => {
    const el = doc.getElementById(id);
    return el && el.textContent && el.textContent.trim() && el.textContent.trim() !== '--';
  });
  // 集合竞价/夜盘时段新浪不给出今日结算价（返回 0），此时显示 -- 属正常
  const settleNa = !App.state.quote.settle;
  check('顶部 12 项明细全部填充', filled.length + (settleNa ? 1 : 0) === 12,
    filled.length + '/12' + (settleNa ? '（结算价夜盘无值，显示 -- 属正常）' : '')
    + (filled.length < 12 ? ' 缺:' + statIds.filter(i => !filled.includes(i)) : ''));
  check('顶部时间已格式化', /^\d{2}:\d{2}:\d{2}$/.test(doc.getElementById('hTime').textContent),
    doc.getElementById('hTime').textContent);

  // 合约列表：无过期、覆盖完整
  const nowYM = new Date().getFullYear() * 100 + (new Date().getMonth() + 1);
  const expired = App.state.symbols.items.filter(it => {
    if (/^[A-Za-z]{1,2}0$/.test(it.code)) return false;   // 主力连续（XX0）无交割月
    if (/^[A-Za-z]{1,2}W$/.test(it.code)) return false;   // 加权指数（XXW）无交割月
    const mm = it.code.match(/(\d{2})(\d{2})$/);
    return !mm || (2000 + Number(mm[1])) * 100 + Number(mm[2]) < nowYM;
  });
  check('合约列表不含已过期合约', expired.length === 0,
    expired.map(x => x.code).join(',') || '无');
  const hasMain = App.state.symbols.items.some(it => it.isMain || /^[A-Za-z]{1,2}0$/.test(it.code));
  const hasWt = App.state.symbols.items.some(it => it.isWeighted);
  check('合约列表覆盖完整（加权指数 + 12 个月份 + 主力连续）',
    App.state.symbols.count >= 14 && hasMain && hasWt,
    App.state.symbols.count + ' 个: ' + App.state.symbols.items.map(x => x.code).join(' '));
  check('加权指数行排在列表第一位', App.state.symbols.items[0].isWeighted,
    App.state.symbols.items[0].code + ' ' + App.state.symbols.items[0].name);

  // 周期按钮点击
  const wk = doc.querySelector('#periodGroup button[data-period="week"]');
  wk.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  await sleep(1500);
  check('点击「周K」按钮生效', App.state.period === 'week' && App.state.bars.length > 0, 'period=' + App.state.period + ' bars=' + App.state.bars.length);
  check('周期按钮高亮跟随', wk.classList.contains('active'));

  // 指标按钮点击
  const dmiBtn = doc.querySelector('#subIndBar button[data-ind="DMI"]');
  dmiBtn.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  check('点击副图二「DMI」按钮生效', App.state.ind === 'DMI' && dmiBtn.classList.contains('active'));

  // 滚轮缩放
  await App.loadChart('day');
  const n0 = App.visibleRange().count;
  doc.getElementById('chart').dispatchEvent(new win.WheelEvent('wheel', { deltaY: -120, clientX: 600, clientY: 300, bubbles: true, cancelable: true }));
  const n1 = App.visibleRange().count;
  check('滚轮缩放改变可视根数', n1 < n0, n0 + ' → ' + n1);
  App.fitAll();
  check('全览恢复全部', App.visibleRange().count === App.state.bars.length, App.visibleRange().count + '');

  // 十字光标
  App.state.hover = { x: 600, y: 200, idx: null, zone: null, inside: true };
  const before = { ...stats };
  try { App.draw(); check('十字光标绘制', stats.fillText > before.fillText); }
  catch (e) { check('十字光标绘制', false, 'EX: ' + (e.stack || e.message)); }

  // 主题切换
  doc.getElementById('btnTheme').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  check('主题切换为 light', doc.documentElement.dataset.theme === 'light', doc.documentElement.dataset.theme);
  doc.getElementById('btnTheme').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));

  console.log('\n========== 7b. K线全量显示 / 缩放平移 ==========');
  {
    // 默认必须显示全量（此前日/周/月/年只给 120 根，看起来像"数据没显示全"）
    await App.loadChart('day');
    await sleep(300);
    const total = App.state.bars.length;
    const vis = App.visibleRange();
    check('日K 默认显示全量（非截断）', vis.count === total && total > 300,
      total + ' 根全显示');
    check('日K 全量根数达到多年历史（≥1000）', total >= 1000, total + ' 根');

    // 周/月/年K 也应为全量
    for (const per of ['week', 'month', 'year']) {
      await App.loadChart(per);
      await sleep(200);
      const t = App.state.bars.length;
      const v = App.visibleRange();
      check(per + 'K 默认显示全量', v.count === t && t > 0, t + ' 根');
    }

    // 滚轮缩放：缩小 -> 显示更少；放大 -> 恢复更多
    await App.loadChart('day');
    await sleep(200);
    const n0 = App.visibleRange().count;
    const chart = doc.getElementById('chart');
    chart.dispatchEvent(new win.WheelEvent('wheel', { deltaY: -120, clientX: 600, clientY: 300, bubbles: true, cancelable: true }));
    const n1 = App.visibleRange().count;
    check('滚轮放大：可视根数变少', n1 < n0, n0 + ' → ' + n1);
    chart.dispatchEvent(new win.WheelEvent('wheel', { deltaY: 120, clientX: 600, clientY: 300, bubbles: true, cancelable: true }));
    const n2 = App.visibleRange().count;
    check('滚轮缩小：可视根数变多', n2 > n1, n1 + ' → ' + n2);

    // 拖动平移：向左拖 -> viewStart 前移
    App.fitAll();
    chart.dispatchEvent(new win.WheelEvent('wheel', { deltaY: -120, clientX: 600, clientY: 300, bubbles: true, cancelable: true }));
    const startBefore = App.visibleRange().start;
    chart.dispatchEvent(new win.MouseEvent('mousedown', { clientX: 600, clientY: 300, bubbles: true }));
    win.dispatchEvent(new win.MouseEvent('mousemove', { clientX: 500, clientY: 300, bubbles: true }));
    const startAfter = App.visibleRange().start;
    win.dispatchEvent(new win.MouseEvent('mouseup', { clientX: 500, clientY: 300, bubbles: true }));
    check('拖动平移：可视起点前移', startAfter > startBefore,
      startBefore + ' → ' + startAfter);

    // 触屏接口：应已注册且不抛错
    let touchOk = true, touchErr = '';
    try {
      const ts = new win.Event('touchstart');
      ts.touches = [{ clientX: 600, clientY: 300 }];
      chart.dispatchEvent(ts);
      const tm = new win.Event('touchmove');
      tm.touches = [{ clientX: 500, clientY: 300 }];
      chart.dispatchEvent(tm);
      const te = new win.Event('touchend');
      te.touches = [];
      chart.dispatchEvent(te);
    } catch (e) { touchOk = false; touchErr = e.message; }
    check('触屏拖动事件已绑定且不抛错', touchOk, touchErr || 'OK');

    // 分钟线同样默认全量
    await App.loadChart('5');
    await sleep(250);
    const t5 = App.state.bars.length;
    check('5分钟K 默认显示全量', App.visibleRange().count === t5 && t5 > 0, t5 + ' 根');
    await App.loadChart('day');
    await sleep(200);
  }

  console.log('\n========== 7c. 底部数据说明（可折叠）与署名 ==========');
  {
    const foot = doc.getElementById('chartFoot');
    const head = doc.getElementById('cfHead');
    const body = doc.getElementById('cfBody');
    check('底部说明容器存在', !!foot && !!head && !!body);

    // 默认折叠
    check('默认处于折叠状态', !foot.classList.contains('open'),
      'class="' + foot.className + '"');
    check('折叠时为 aria-expanded=false', head.getAttribute('aria-expanded') === 'false',
      head.getAttribute('aria-expanded'));

    // 说明内容必须覆盖关键信息
    const txt = body.textContent || '';
    for (const kw of ['滚轮', '拖动', '数据源', '加权指数', '仓权', '天勤', '不构成任何投资建议']) {
      check('说明包含「' + kw + '」', txt.indexOf(kw) >= 0);
    }

    // 点击展开
    head.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
    check('点击后展开', foot.classList.contains('open'));
    check('展开后 aria-expanded=true', head.getAttribute('aria-expanded') === 'true');
    check('展开状态已持久化', win.localStorage.getItem('sa.footOpen') === '1',
      String(win.localStorage.getItem('sa.footOpen')));

    // 再点折叠
    head.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
    check('再次点击折叠', !foot.classList.contains('open'));
    check('折叠状态已持久化', win.localStorage.getItem('sa.footOpen') === '0',
      String(win.localStorage.getItem('sa.footOpen')));

    // 键盘可达（回车切换）
    head.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    check('回车键可切换展开', foot.classList.contains('open'));
    head.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));

    // 署名
    const sign = doc.querySelector('.cf-sign');
    check('底部含署名', !!sign, sign ? sign.textContent.trim() : '无');
    const st = sign ? sign.textContent : '';
    check('署名含「设计：公歧子」', st.indexOf('公歧子') >= 0, st.trim());
    check('署名含微信号 gongqizi0', st.indexOf('gongqizi0') >= 0);
    check('署名含「微信」字样', st.indexOf('微信') >= 0);
  }

  console.log('\n========== 8. 运行期错误 ==========');
  // 忽略 jsdom 未实现的 API 噪音
  const real = errors.filter(e => !/Not implemented|Could not parse CSS|navigation \(except hash changes\)/i.test(e));
  check('无运行期 JS 错误', real.length === 0, real.slice(0, 5).join(' | ') || '无');
  if (errors.length) console.log('  （已忽略的 jsdom 未实现提示 ' + (errors.length - real.length) + ' 条）');

  const failed = results.filter(r => !r.pass);
  console.log('\n================ 汇总 ================');
  console.log('  总计 ' + results.length + ' 项，通过 ' + (results.length - failed.length) + ' 项，失败 ' + failed.length + ' 项');
  if (failed.length) failed.forEach(f => console.log('   ✗ ' + f.name + ' → ' + f.extra));
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error('测试脚本异常:', e); process.exit(2); });
