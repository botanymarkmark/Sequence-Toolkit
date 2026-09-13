# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台、剔除未使用的重量级模块。

简报中的 ``icon="assets/icon.ico"`` 已移除：仓库内没有该图标文件，
而 PyInstaller 对不存在的图标路径会直接报错中止打包。
日后补上图标时可把下面被注释的一行恢复。
"""

EXCLUDES = [
    "numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest",
    "IPython", "notebook", "PyQt5", "PySide2", "PySide6", "wx",
    "setuptools", "pip", "wheel", "distutils", "unittest", "pydoc",
    "http.server", "xmlrpc", "sqlite3", "bz2", "lzma",
]
# 注意：不要剔除 "email"。urllib.request（经 http.client）在导入时就会
# `import email.parser`，剔除它会让打包后的程序在启动瞬间抛
# ModuleNotFoundError: No module named 'email'，窗口根本开不出来。
# 同理 "html" 保留在集合外——http.client/http.cookiejar 的部分路径会用到它。

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="序列工具箱",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # icon="assets/icon.ico",  # 仓库暂无图标文件，恢复此行前请先放入 assets/icon.ico
)
