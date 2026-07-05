# -*- mode: python ; coding: utf-8 -*-
import os
import airportsdata
from PyInstaller.utils.hooks import collect_all, collect_submodules

airportsdata_dir = os.path.dirname(airportsdata.__file__)

# numpy 전체 수집 (numpy C-extension 누락 문제 해결)
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=numpy_binaries,
    datas=[
        ('static', 'static'),
        ('examples', 'examples'),
        (airportsdata_dir, 'airportsdata'),
    ] + numpy_datas,
    hiddenimports=numpy_hiddenimports + [
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'multipart',
        'multipart.multipart',
        'data_processor',
        'func_ubkais',
        'airportsdata',
        'openpyxl',
        'pytz',
        'pandas',
        'pandas.core',
        'pandas.core.arrays',
        'pandas.core.dtypes',
        'pandas.core.indexes',
        'pandas.io.formats.style',
        'pandas.plotting',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'tensorboard',
        'scipy', 'sympy',
        'matplotlib', 'PIL', 'Pillow',
        'cv2', 'opencv-python',
        'tkinter', '_tkinter',
        'lxml',
        'numba', 'llvmlite',
        'pyarrow',
        'imageio', 'imageio_ffmpeg',
        'pygments',
        'sqlalchemy',
        'cryptography',
        'win32com', 'pythoncom', 'pywintypes',
        'IPython', 'jupyter', 'notebook',
        'pytest', 'unittest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BarChartCreator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BarChartCreator',
)
