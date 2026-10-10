# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 · 国内期货行情面板（单文件 EXE）

构建：
    # 个人版（内置自己的快期账号，仅供自用，切勿公开分发）
    C:/Python314/python.exe -m PyInstaller --clean --noconfirm 期货行情面板.spec

    # 公开版（不内置任何凭据，可安全上传 GitHub Release）
    set PANEL_PUBLIC_BUILD=1
    C:/Python314/python.exe -m PyInstaller --clean --noconfirm 期货行情面板.spec

要点：
  · console=True —— 保留控制台，启动时能看到面板地址/行情连通状态，出错也可读
  · 只读资源 index.html / tianqin.json 打进 exe（运行时落在 sys._MEIPASS）
  · tianqin.json 同时打进内置一份作为"出厂默认账号"；exe 同目录若存在外置
    tianqin.json 则优先生效（见 weighted_index._resolve_tq_config_path）
  · tqsdk 采用惰性导入，附带的 hook 会自动收 web/ 与 expired_quotes.json.lzma
  · 排除用不到的重型库，压缩体积

⚠ 安全提醒（一定要读）
  PyInstaller 的归档**不是加密**，打进去的 tianqin.json 可以用几行代码取出明文：
      from PyInstaller.archive.readers import CArchiveReader
      import zlib
      print(zlib.decompress(CArchiveReader('xx.exe').extract('tianqin.json')).decode())
  所以**公开发布必须走 PANEL_PUBLIC_BUILD=1**，内置账号只用于自己本机使用。
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.abspath(os.path.dirname(SPEC))          # noqa: F821  (SPEC 由 PyInstaller 注入)

# 公开版开关：置 1 时不内置账号（用 tianqin.public.json 冒充 tianqin.json 打进去）
PUBLIC_BUILD = os.environ.get('PANEL_PUBLIC_BUILD', '').strip() == '1'

if PUBLIC_BUILD:
    # datas 不支持重命名，所以先把备用文件拷成名为 tianqin.json 的暂存副本再打进去
    _stage = os.path.join(HERE, '_public_stage')
    os.makedirs(_stage, exist_ok=True)
    _src = os.path.join(HERE, 'tianqin.public.json')
    with open(_src, 'rb') as _f:
        _payload = _f.read()
    with open(os.path.join(_stage, 'tianqin.json'), 'wb') as _f:
        _f.write(_payload)
    TQ_JSON = os.path.join(_stage, 'tianqin.json')
    EXE_NAME = '期货行情面板-公开版'
else:
    TQ_JSON = os.path.join(HERE, 'tianqin.json')
    EXE_NAME = '期货行情面板'

# 需要随包携带的只读资源
datas = [
    (os.path.join(HERE, 'index.html'), '.'),
    (TQ_JSON, '.'),
]

# tqsdk 是惰性导入（函数内 import），静态分析扫不到 → 显式声明。
# numpy / pandas 等是 tqsdk/api.py 的**顶层强依赖**，必须打进包，
# 否则 import tqsdk 会 ImportError（见 pyinstaller_hooks/hook-tqsdk.py 注释）。
hiddenimports = collect_submodules('tqsdk') + [
    'weighted_index',
    'numpy', 'pandas', 'pandas._libs', 'pandas._libs.internals',
    'psutil',
    'sgqlc', 'sgqlc.operation',
    'shinny_structlog', 'simplejson',
    'aiohttp', 'aiohappyeyeballs',
    'yarl', 'multidict', 'frozenlist', 'propcache', 'attr', 'attrs',
    'websockets', 'websocket', 'requests', 'filelock',
    'Crypto', 'jwt', 'packaging',
]

# 自定义 hook 目录：补齐 tqsdk 的第三方依赖（tqsdk 自带 hook 只收 datas）
HOOK_DIR = os.path.join(HERE, 'pyinstaller_hooks')


# 明确排除：本程序只用标准库 + tqsdk，这些都用不上，排掉可瘦身
#
# ⚠ 两条踩过的坑，务必保留这两个注释约束：
#
# 1) **绝不能排除 numpy / pandas / scipy**
#    tqsdk/api.py 第 39/44 行是无保护的 `import numpy as np` / `import pandas as pd`
#    （还有 `from pandas._libs.internals import BlockPlacement`），排除后打包结果里
#    `import tqsdk` 直接 ImportError → /api/tq/status 恒为 installed:false。
#
# 2) **绝不能排除 unittest / pydoc / doctest / test 等标准库**
#    虽然 tqsdk 自己不 import unittest，但它的依赖链会走到
#    numpy.testing._private.utils，那里是**顶层** `import unittest`。
#    曾把 unittest 放进 excludes，导致打包后报
#    `ModuleNotFoundError: No module named 'unittest'`，天勤档同样不可用。
#    标准库本来就不占多少体积，不值得为它冒险。
excludes = [
    'matplotlib', 'PIL', 'cv2',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
    'IPython', 'jupyter', 'notebook', 'pytest',
    'flask', 'werkzeug', 'jinja2', 'click', 'itsdangerous',   # 本程序不用 Flask
    'setuptools', 'pip', 'wheel',
]

a = Analysis(
    ['server.py'],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[HOOK_DIR],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,              # 保留黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
