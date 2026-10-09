# -*- mode: python ; coding: utf-8 -*-
"""tqsdk 的补充 PyInstaller hook。

背景（踩坑记录）：
    tqsdk 在本项目里是**惰性导入**（weighted_index.py 函数体内 `import tqsdk`），
    PyInstaller 的静态分析扫不到这条导入链，于是 `tqsdk/api.py` 自己的顶层
    `from sgqlc.operation import Operation`、`from shinny_structlog import ...`
    等依赖不会被收进来 → 打包后 `import tqsdk` 直接 ImportError，
    /api/tq/status 永远返回 installed:false（"天勤"档不可用）。

    tqsdk 自带的 hook 只负责 datas（web / expired_quotes.json.lzma）与
    tqsdk_ctpse 子模块，**不处理**这些第三方依赖，所以这里补一份。

本 hook 由 spec 的 hookspath 指向本目录而生效。
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# tqsdk/api.py 的顶层第三方依赖（已逐一核对源码）
hiddenimports = [
    'numpy',
    'pandas',
    'pandas._libs',
    'pandas._libs.internals',
    'psutil',
    'sgqlc',
    'sgqlc.operation',
    'shinny_structlog',
    'aiohttp',
    'requests',
    'packaging',
]

# 连带的传递依赖，宁多勿缺（体积影响很小）
hiddenimports += collect_submodules('sgqlc')
hiddenimports += [
    'shinny_structlog.shm',
    'simplejson',
    'websocket',
    'websockets',
    'multidict',
    'yarl',
    'frozenlist',
    'propcache',
    'attr',
    'attrs',
    'aiohappyeyeballs',
    'filelock',
]

datas = collect_data_files('tqsdk', includes=['web', 'expired_quotes.json.lzma'])
