# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows x64，单文件 exe）。

用法：
    pip install -r requirements.txt pyinstaller
    pyinstaller build.spec --noconfirm --clean

adb 会从当前虚拟环境的 adbutils 里打包；鸿蒙的 hdc 是可选资源，
没有就跳过（可用环境变量 HDC_DIR 指定 hdc.exe 所在目录）。
"""
import os

block_cipher = None
HERE = os.path.abspath('.')
SITE = os.path.join(HERE, '.venv', 'Lib', 'site-packages')

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [('version.json', '.')]

# 芭芭农场面板是 canvas，滚动后无障碍树不刷新，只能靠 OCR 读任务行，
# 所以 exe 里必须带上 rapidocr 的模型文件（约 200MB）
datas += collect_data_files('rapidocr_onnxruntime')


def add_file(src, dst):
    if os.path.isfile(src):
        datas.append((src, dst))
    else:
        print(f'[build] 跳过不存在的文件: {src}')


def add_dir(src, dst):
    if os.path.isdir(src):
        datas.append((src, dst))
    else:
        print(f'[build] 跳过不存在的目录: {src}')


# adb（安卓必需，来自 adbutils 自带的 binaries）
adb_dir = os.path.join(SITE, 'adbutils', 'binaries')
for _name in ('adb.exe', 'AdbWinApi.dll', 'AdbWinUsbApi.dll'):
    add_file(os.path.join(adb_dir, _name), 'tools')

# uiautomator2 运行时资源（设备端 apk + jar）
add_dir(os.path.join(SITE, 'uiautomator2', 'assets'), os.path.join('uiautomator2', 'assets'))

# 鸿蒙资源（可选，未安装则跳过）
add_dir(os.path.join(SITE, 'hmdriver2', 'assets'), os.path.join('hmdriver2', 'assets'))
add_file(os.path.join(os.environ.get('HDC_DIR', ''), 'hdc.exe'), 'tools')

hiddenimports = [
    'uiautomator2',
    'adbutils',
    'lxml',
    'lxml.etree',
    'lxml._elementpath',
    'requests',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'idna',
    'PIL',
    'PIL.Image',
    'retry',
    'decorator',
    'deprecation',
    'modules.device_adapter',
    'modules.ui',
    'modules.activity',
    'modules.taobao',
    'modules.energy',
    'modules.farm',
    'modules.ocr',
    'modules.captcha',
    'modules.utils',
    'onnxruntime',
    'cv2',
    'shapely',
    'pyclipper',
    'yaml',
] + collect_submodules('rapidocr_onnxruntime')

a = Analysis(
    ['main.py'],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=(['hmdriver2'] if not os.path.isdir(os.path.join(SITE, 'hmdriver2')) else [])
    + ['tkinter', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='任务助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
