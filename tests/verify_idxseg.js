/* 指数口径分段控件专项校验：渲染、点击、禁用、持久化 */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const HTML = path.join(__dirname, '..', 'index.html');
const BASE = process.env.BASE || 'http://127.0.0.1:8686';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(String(e && (e.stack || e.message || e))));
vc.on('error', (...a) => errors.push(a.map(String).join(' ')));

const results = [];
const check = (n, c, x) => {
  results.push({ n, c: !!c });
  console.log((c ? '  [PASS] ' : '  [FAIL] ') + n + (x !== undefined ? '  → ' + x : ''));
};

function makeCtx() {
  const noop = () => {};
  const grad = { addColorStop: noop };
  const c = new Proxy({
    canvas: null, measureText: () => ({ width: 40 }),
    createLinearGradient: () => grad, createRadialGradient: () => grad,
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
  }, { get: (t, k) => (k in t ? t[k] : noop) });
  return c;
}

(async () => {
  const dom = new JSDOM(fs.readFileSync(HTML, 'utf8'), {
    url: BASE + '/', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) {
      win.fetch = (u, o) => fetch(String(u).startsWith('http') ? String(u) : BASE + String(u), o);
      win.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
      win.HTMLCanvasElement.prototype.getContext = function () {
        if (!this.__ctx) { this.__ctx = makeCtx(); this.__ctx.canvas = this; }
        return this.__ctx;
      };
      win.Element.prototype.getBoundingClientRect = () =>
        ({ x: 0, y: 0, left: 0, top: 0, right: 1200, bottom: 700, width: 1200, height: 700 });
      win.devicePixelRatio = 1;
    },
  });
  const win = dom.window, doc = win.document;

  // 等初次加载完成
  let w0 = 0;
  while (!(win.App && win.App.state.symbols && win.App.state.symbols.count) && w0 < 60000) {
    await sleep(250); w0 += 250;
  }
  const A = win.App;
  check('App 已挂到 window（内联调用可用）', typeof win.App === 'object', typeof win.App);

  const seg = doc.getElementById('idxSeg');
  check('分段控件存在于 DOM', !!seg);
  const btns = seg ? [...seg.querySelectorAll('button')] : [];
  check('包含三档按钮 oi/vol/tianqin',
    btns.length === 3 && btns.map(b => b.dataset.wm).join(',') === 'oi,vol,tianqin',
    btns.map(b => b.dataset.wm).join(','));

  // 默认高亮 = 仓权
  const onNow = btns.filter(b => b.classList.contains('on')).map(b => b.dataset.wm);
  check('默认高亮「仓权」', onNow.length === 1 && onNow[0] === 'oi', onNow.join(','));

  // 天勤按钮可用性
  const tqBtn = btns.find(b => b.dataset.wm === 'tianqin');
  check('天勤按钮可用性与探测一致',
    !!tqBtn && (tqBtn.disabled !== !!A.state.tqOk),
    'disabled=' + (tqBtn && tqBtn.disabled) + ' tqOk=' + A.state.tqOk);

  // 点击「量权」→ 高亮切换 + 列表口径变化
  btns.find(b => b.dataset.wm === 'vol').dispatchEvent(
    new win.MouseEvent('click', { bubbles: true }));
  let w1 = 0;
  while (!(A.state.symbols && A.state.symbols.weightMode === 'vol') && w1 < 40000) {
    await sleep(200); w1 += 200;
  }
  check('点击「量权」后列表切到 vol', A.state.symbols.weightMode === 'vol',
    A.state.symbols.weightMode);
  const onVol = [...seg.querySelectorAll('button')].filter(b => b.classList.contains('on'))
    .map(b => b.dataset.wm);
  check('高亮跟随切到「量权」', onVol.join(',') === 'vol', onVol.join(','));
  check('底部说明文字已更新为量权口径',
    doc.getElementById('sideFoot').textContent.indexOf('成交量加权') >= 0,
    doc.getElementById('sideFoot').textContent);

  // 点击「仓权」回退
  [...seg.querySelectorAll('button')].find(b => b.dataset.wm === 'oi').dispatchEvent(
    new win.MouseEvent('click', { bubbles: true }));
  let w2 = 0;
  while (!(A.state.symbols && A.state.symbols.weightMode === 'oi') && w2 < 40000) {
    await sleep(200); w2 += 200;
  }
  check('点击「仓权」回退到 oi', A.state.symbols.weightMode === 'oi', A.state.symbols.weightMode);

  // 参数校验：非法值回落到 oi
  await A.setWeightMode('bogus');
  check('非法口径自动回落为 oi', A.state.weightMode === 'oi', A.state.weightMode);

  // 持久化：localStorage 应记录当前口径
  // 天勤档：可用时必须能真正切过去（并回退）
  if (A.state.tqOk) {
    [...seg.querySelectorAll('button')].find(b => b.dataset.wm === 'tianqin').dispatchEvent(
      new win.MouseEvent('click', { bubbles: true }));
    let w3 = 0;
    while (!(A.state.symbols && A.state.symbols.weightMode === 'tianqin') && w3 < 60000) {
      await sleep(250); w3 += 250;
    }
    const tw = A.state.symbols && A.state.symbols.items.find(i => i.isWeighted);
    check('点击「天勤」后列表切到 tianqin', A.state.symbols.weightMode === 'tianqin',
      A.state.symbols.weightMode);
    check('天勤档加权行来源为 tianqin', !!(tw && tw.source === 'tianqin'),
      tw ? tw.source + ' ' + tw.name + ' ' + tw.last : '无');
    check('天勤档主连行已并入', !!A.state.symbols.items.find(i => i.isMain && i.source === 'tianqin'),
      (A.state.symbols.items.find(i => i.isMain && i.source === 'tianqin') || {}).code || '无');
    await A.setWeightMode('oi');
    check('天勤档可回退到 oi', A.state.weightMode === 'oi', A.state.weightMode);
  } else {
    const tb = [...seg.querySelectorAll('button')].find(b => b.dataset.wm === 'tianqin');
    check('天勤未就绪时按钮禁用', !!tb && tb.disabled, 'disabled=' + (tb && tb.disabled));
  }

  check('口径已写入 localStorage',
    win.localStorage.getItem('sa.weightMode') === 'oi',
    win.localStorage.getItem('sa.weightMode'));

  check('无运行期 JS 错误', errors.filter(e => !/not implemented/i.test(e)).length === 0,
    errors.filter(e => !/not implemented/i.test(e)).slice(0, 2).join(' | '));

  const pass = results.filter(r => r.c).length;
  console.log('\n  总计 ' + results.length + ' 项，通过 ' + pass + ' 项，失败 '
    + (results.length - pass) + ' 项');
  win.close();
  process.exit(pass === results.length ? 0 : 1);
})();
