from pathlib import Path
from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


base = Path(SPECPATH)
playwright = Path(find_spec('playwright').origin).parent
analysis = Analysis(
    [str(base / 'src' / 'launcher.py')],
    pathex=[str(base / 'src')],
    datas=[(str(playwright / 'driver'), 'playwright/driver'), (str(base / 'assets'), 'assets')] +
          collect_data_files('tkinterdnd2', includes=['tkdnd/win-x64/**', 'tkdnd/win-x64-tcl9/**']),
    hiddenimports=collect_submodules('gallery_dl'),
    excludes=['IPython', 'matplotlib', 'numpy', 'scipy', 'pandas', 'pytest', 'PySide6', 'PyQt6'],
)
archive = PYZ(analysis.pure)
app = EXE(archive, analysis.scripts, [], exclude_binaries=True,
          name='图影盒', console=False, icon=str(base / 'assets' / 'app.ico'),
          manifest=str(base / 'app.manifest'), upx=False)
gallery = EXE(archive, analysis.scripts, [('X utf8', None, 'OPTION')], exclude_binaries=True,
              name='gallery-worker', console=True, upx=False)
release = COLLECT(app, gallery, analysis.binaries, analysis.datas, name='图影盒v1.0-便携版', upx=False)
