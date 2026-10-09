# -*- coding: utf-8 -*-
"""独立实现 周/月/年 K 合成，与前端 JS 的结果逐根比对（交叉验证）"""
import json, os, sys, io
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(HERE, name), encoding='utf-8') as f:
        return json.load(f)


def week_start(d):
    return (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d')


def group(bars, keyfn):
    out, cur, curkey = [], None, None
    for b in bars:
        k = keyfn(b['t'])
        if k != curkey:
            if cur:
                out.append(cur)
            cur = {'t': b['t'], 'o': b['o'], 'h': b['h'], 'l': b['l'], 'c': b['c'],
                   'v': b['v'], 'oi': b['oi'], 'cnt': 1}
            curkey = k
        else:
            cur['h'] = max(cur['h'], b['h'])
            cur['l'] = min(cur['l'], b['l'])
            cur['c'] = b['c']
            cur['v'] += b['v']
            cur['oi'] = b['oi']
            cur['cnt'] += 1
    if cur:
        out.append(cur)
    return out


def main():
    daily = load('daily_raw.json')
    print("日K 原始根数：%d  （%s ~ %s）\n" % (len(daily), daily[0]['t'], daily[-1]['t']))

    specs = [
        ('week',  lambda t: week_start(datetime.strptime(t, '%Y-%m-%d'))),
        ('month', lambda t: t[:7]),
        ('year',  lambda t: t[:4]),
    ]

    allok = True
    for name, fn in specs:
        exp = load('front_%s.json' % name)
        got = group(daily, fn)
        print("── %-5s  前端 %d 根 / 独立实现 %d 根" % (name, len(exp), len(got)))
        if len(exp) != len(got):
            print("   ✗ 根数不一致！")
            allok = False
            continue
        bad = 0
        for i, (a, b) in enumerate(zip(exp, got)):
            for f in ('o', 'h', 'l', 'c', 'v', 'oi'):
                if abs(float(a[f]) - float(b[f])) > 1e-6:
                    print("   ✗ 第%d根 %s 字段 %s：前端=%s 应为=%s" % (i, a['t'], f, a[f], b[f]))
                    bad += 1
                    allok = False
            if a['t'] != b['t']:
                print("   ✗ 第%d根起始日：前端=%s 应为=%s" % (i, a['t'], b['t']))
                bad += 1
                allok = False
            # 内部一致性：o/h/l/c 关系
            if not (b['l'] <= min(b['o'], b['c']) and b['h'] >= max(b['o'], b['c'])):
                print("   ✗ 第%d根 %s OHLC 关系异常" % (i, a['t']))
                bad += 1
                allok = False
        if bad == 0:
            print("   ✓ 全部 %d 根 OHLCV+持仓 完全一致" % len(exp))
            # 抽样打印
            for i in [0, len(exp) // 2, len(exp) - 1]:
                b = exp[i]
                print("     [%2d] %s  开%-8s 高%-8s 低%-8s 收%-8s 量%-10s 仓%-10s"
                      % (i, b['t'], b['o'], b['h'], b['l'], b['c'], b['v'], b['oi']))
        print()

    # 汇总校验：月K 成交量之和应等于日K 成交量之和
    dv = sum(b['v'] for b in daily)
    mv = sum(b['v'] for b in load('front_month.json'))
    yv = sum(b['v'] for b in load('front_year.json'))
    print("── 总量守恒 ──")
    print("   日K 成交量合计   = %d" % dv)
    print("   月K 成交量合计   = %d  %s" % (mv, '✓' if mv == dv else '✗ 不守恒'))
    print("   年K 成交量合计   = %d  %s" % (yv, '✓' if yv == dv else '✗ 不守恒'))
    if mv != dv or yv != dv:
        allok = False

    print()
    print("=" * 56)
    print("  交叉验证结果：%s" % ("全部通过 ✓" if allok else "存在不一致 ✗"))
    print("=" * 56)
    return 0 if allok else 1


if __name__ == '__main__':
    raise SystemExit(main())
