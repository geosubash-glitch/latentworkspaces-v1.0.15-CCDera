# PyInstaller spec for Latent Studio.
# Build from the repository root:   pyinstaller packaging/latent.spec --noconfirm
# Produces dist/Latent Studio/ (Windows, Linux) or dist/Latent Studio.app (macOS).
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "latent", "assets")
APP_NAME = "Latent Studio"

a = Analysis(
    [os.path.join(ROOT, "run_latent.py")],
    pathex=[ROOT],
    datas=[(ASSETS, os.path.join("latent", "assets"))],
    hiddenimports=["PIL._tkinter_finder"],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "PyQt5", "PySide2", "PyQt6", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)


def _windows_version_file():
    """File properties shown in Windows Explorer (Details tab)."""
    parts = [int(p) for p in __version__.split(".")[:3]] + [0]
    ver = tuple((parts + [0, 0, 0, 0])[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={ver}, prodvers={ver}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Latent Studio'),
      StringStruct('FileDescription', 'Latent Studio - analog film workstation'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'Latent Studio'),
      StringStruct('OriginalFilename', 'Latent Studio.exe'),
      StringStruct('ProductName', 'Latent Studio'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = os.path.join(workpath, "version_info.txt")
    os.makedirs(workpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path

sys.path.insert(0, ROOT)
from latent import __version__

icon = os.path.join(ASSETS, "app_logo.ico")
if sys.platform == "darwin" and os.path.exists(os.path.join(ASSETS, "app_logo.icns")):
    icon = os.path.join(ASSETS, "app_logo.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=icon,
    upx=False,
    version=_windows_version_file() if sys.platform.startswith("win") else None,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="studio.latent.app",
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
