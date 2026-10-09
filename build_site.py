# -*- coding: utf-8 -*-
"""把 docs/*.md 转成与站点同风格的 HTML（输出到 site/）。

只依赖标准库。支持本项目文档实际用到的 Markdown 子集：
标题、粗体、行内码、围栏代码块、表格、有序/无序列表、引用块、链接、水平线。
"""
import os
import re
import html as _html

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
OUT = os.path.join(HERE, "site")

PAGE = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · 国内期货行情面板</title>
<meta name="description" content="{desc}">
<style>
:root{{
  --bg:#0d1117;--bg2:#161b22;--bg3:#1c2333;--bd:#30363d;
  --fg:#e6edf3;--fg2:#8b949e;--fg3:#6e7681;
  --acc:#f0883e;--acc2:#58a6ff;--code-bg:#161b22;
}}
html[data-theme="light"]{{
  --bg:#fff;--bg2:#f6f8fa;--bg3:#eef2f7;--bd:#d0d7de;
  --fg:#1f2328;--fg2:#59636e;--fg3:#818b98;
  --acc:#bc4c00;--acc2:#0969da;--code-bg:#f6f8fa;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--fg);line-height:1.78;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased}}
a{{color:var(--acc2);text-decoration:none}}
a:hover{{text-decoration:underline}}
header{{position:sticky;top:0;z-index:50;background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--bd)}}
header .bar{{max-width:900px;margin:0 auto;padding:0 22px;display:flex;align-items:center;
  gap:16px;height:58px;font-size:14px}}
header .logo{{font-weight:700;font-size:15px;white-space:nowrap;display:flex;align-items:center;gap:8px}}
header .logo i{{width:8px;height:8px;border-radius:50%;background:var(--acc);
  box-shadow:0 0 9px var(--acc);display:block}}
header nav{{margin-left:auto;display:flex;gap:18px;align-items:center}}
header nav a{{color:var(--fg2)}}
header nav a:hover{{color:var(--fg);text-decoration:none}}
#themeBtn{{background:var(--bg3);border:1px solid var(--bd);color:var(--fg2);
  border-radius:7px;padding:5px 11px;cursor:pointer;font-size:12.5px;font-family:inherit}}
#themeBtn:hover{{color:var(--fg);border-color:var(--fg3)}}
main{{max-width:900px;margin:0 auto;padding:38px 22px 70px}}
h1{{font-size:clamp(25px,4vw,34px);font-weight:800;letter-spacing:-.02em;
  line-height:1.28;margin:8px 0 10px;padding-bottom:20px;border-bottom:1px solid var(--bd)}}
h2{{font-size:21px;font-weight:700;margin:44px 0 12px;letter-spacing:-.01em;
  padding-top:6px;scroll-margin-top:74px}}
h3{{font-size:17px;font-weight:650;margin:30px 0 10px;scroll-margin-top:74px}}
h4{{font-size:15px;font-weight:650;margin:22px 0 8px}}
p{{margin:12px 0;color:var(--fg)}}
strong{{font-weight:650;color:var(--fg)}}
ul,ol{{margin:12px 0 12px 24px}}
li{{margin:6px 0;color:var(--fg2)}}
li strong,li b{{color:var(--fg)}}
hr{{border:0;border-top:1px solid var(--bd);margin:38px 0}}
blockquote{{border-left:3px solid var(--acc);background:var(--bg2);
  border-radius:0 8px 8px 0;padding:12px 18px;margin:16px 0;color:var(--fg2)}}
blockquote p{{margin:5px 0;color:var(--fg2)}}
pre{{background:var(--code-bg);border:1px solid var(--bd);border-radius:9px;
  padding:15px 17px;overflow-x:auto;font-size:13px;line-height:1.68;margin:15px 0}}
pre code{{font-size:13px}}
code{{font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}}
p code,li code,td code,th code{{background:var(--bg3);border:1px solid var(--bd);
  border-radius:4px;padding:1.5px 5.5px;font-size:12.5px;color:var(--acc)}}
pre code{{background:none;border:0;color:var(--fg);padding:0}}
.tw{{overflow-x:auto;margin:16px 0}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;min-width:420px}}
th,td{{padding:9px 13px;text-align:left;border-bottom:1px solid var(--bd)}}
th{{color:var(--fg2);font-weight:600;font-size:12.5px;background:var(--bg2);white-space:nowrap}}
tbody tr:hover{{background:var(--bg2)}}
td{{color:var(--fg2)}}
td b,td strong{{color:var(--fg)}}
.toc{{background:var(--bg2);border:1px solid var(--bd);border-radius:11px;
  padding:16px 22px;margin:24px 0}}
.toc-h{{font-size:13px;font-weight:700;color:var(--fg2);text-transform:uppercase;
  letter-spacing:.05em;margin-bottom:9px}}
.toc ol{{margin:0 0 0 20px}}
.toc li{{margin:4px 0;font-size:14px}}
footer{{border-top:1px solid var(--bd);padding:26px 0;max-width:900px;margin:0 auto;
  padding-left:22px;padding-right:22px;font-size:13.5px;color:var(--fg3)}}
footer .sign b{{color:var(--acc)}}
#wx{{cursor:pointer;border-bottom:1px dashed var(--fg3)}}
#wx:hover{{color:var(--acc)}}
footer .row{{display:flex;flex-wrap:wrap;gap:8px 20px;margin-bottom:10px}}
</style>
</head>
<body>
<header>
  <div class="bar">
    <div class="logo"><i></i>国内期货行情面板</div>
    <nav>
      <a href="index.html">首页</a>
      <a href="usage.html">使用说明</a>
      <a href="datasource.html">数据源说明</a>
      <a href="https://github.com/chenzhuanxin/domestic-futures-panel" target="_blank" rel="noopener">GitHub</a>
      <button id="themeBtn" type="button">切换主题</button>
    </nav>
  </div>
</header>
<main>
{body}
</main>
<footer>
  <div class="row">
    <a href="index.html">首页</a>
    <a href="usage.html">使用说明</a>
    <a href="datasource.html">数据源说明</a>
    <a href="https://github.com/chenzhuanxin/domestic-futures-panel" target="_blank" rel="noopener">源码仓库</a>
  </div>
  <div class="sign">设计：<b>公歧子</b>　微信：<span id="wx" title="点击复制微信号">gongqizi0</span></div>
</footer>
<script>
(function(){{
  var root=document.documentElement,btn=document.getElementById('themeBtn'),saved=null;
  try{{saved=localStorage.getItem('site.theme');}}catch(e){{}}
  if(saved)root.dataset.theme=saved;
  function sync(){{btn.textContent=root.dataset.theme==='dark'?'浅色模式':'深色模式';}}
  sync();
  btn.addEventListener('click',function(){{
    root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';
    try{{localStorage.setItem('site.theme',root.dataset.theme);}}catch(e){{}}
    sync();
  }});
  var wx=document.getElementById('wx');
  if(wx)wx.addEventListener('click',function(){{
    var t='gongqizi0',old=wx.textContent;
    var done=function(){{wx.textContent='已复制 '+t;
      setTimeout(function(){{wx.textContent=old;}},1400);}};
    if(navigator.clipboard&&navigator.clipboard.writeText){{
      navigator.clipboard.writeText(t).then(done,done);
    }}else{{
      var ta=document.createElement('textarea');ta.value=t;
      ta.style.position='fixed';ta.style.opacity='0';
      document.body.appendChild(ta);ta.select();
      try{{document.execCommand('copy');}}catch(e){{}}
      document.body.removeChild(ta);done();
    }}
  }});
}})();
</script>
</body>
</html>
"""


def esc(t: str) -> str:
    return _html.escape(t, quote=False)


def inline(t: str) -> str:
    """行内元素：先占位保护 code，再处理粗体/链接，最后还原 code。"""
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    t = re.sub(r"`([^`]+)`", stash, t)
    t = esc(t)
    # 链接 [text](url)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
               lambda m: '<a href="%s"%s>%s</a>' % (
                   m.group(2),
                   ' target="_blank" rel="noopener"' if m.group(2).startswith("http") else "",
                   m.group(1)),
               t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    for i, c in enumerate(codes):
        t = t.replace("\x00%d\x00" % i, "<code>%s</code>" % esc(c))
    return t


def slug(t: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", t).strip("-").lower()
    return "h-" + (s or "x")


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out, i = [], 0
    n = len(lines)
    while i < n:
        ln = lines[i]

        # 围栏代码块
        if ln.strip().startswith("```"):
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % esc("\n".join(buf)))
            continue

        # 表格
        if "|" in ln and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1] or ""):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            h = "".join("<th>%s</th>" % inline(c) for c in head)
            body = "".join(
                "<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>"
                for r in rows)
            out.append('<div class="tw"><table><thead><tr>%s</tr></thead>'
                       "<tbody>%s</tbody></table></div>" % (h, body))
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            lv = len(m.group(1))
            txt = m.group(2).strip()
            out.append("<h%d id=\"%s\">%s</h%d>" % (lv, slug(txt), inline(txt), lv))
            i += 1
            continue

        # 水平线
        if re.match(r"^\s*(---|\*\*\*|___)\s*$", ln):
            out.append("<hr>")
            i += 1
            continue

        # 引用块
        if ln.strip().startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            inner = "".join("<p>%s</p>" % inline(b) for b in buf if b)
            out.append("<blockquote>%s</blockquote>" % inner)
            continue

        # 有序列表
        if re.match(r"^\s*\d+\.\s+", ln):
            buf = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                buf.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % inline(b) for b in buf))
            continue

        # 无序列表
        if re.match(r"^\s*[-*]\s+", ln):
            buf = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                buf.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(b) for b in buf))
            continue

        # 空行
        if not ln.strip():
            i += 1
            continue

        # 段落
        out.append("<p>%s</p>" % inline(ln.strip()))
        i += 1

    return "\n".join(out)


def build(md_name: str, out_name: str, title: str, desc: str):
    src = os.path.join(DOCS, md_name)
    with open(src, "r", encoding="utf-8") as fh:
        md = fh.read()
    body = md_to_html(md)
    page = PAGE.format(title=title, desc=desc, body=body)
    dst = os.path.join(OUT, out_name)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(page)
    return dst, len(page.encode("utf-8"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for args in [
        ("使用说明.md", "usage.html", "使用说明",
         "国内期货行情面板完整使用说明：安装运行、界面导览、行情字段、周期与指标、加权指数、全部操作、常见问题。"),
        ("数据源说明.md", "datasource.html", "数据源说明",
         "国内期货行情面板数据源说明：新浪财经各接口的URL/参数/字段/口径，天勤KQ.i/KQ.m对接，加权指数算法与缓存策略。"),
    ]:
        p, sz = build(*args)
        print("  %-16s → %-16s %8.1f KB" % (args[0], args[1], sz / 1024))
    print("完成")
