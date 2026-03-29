# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Game Port Installer.

Build with:
    pyinstaller GamePortInstaller.spec

The resulting .app will be in dist/Game Port Installer.app
"""

from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Scraper registry loads these by name at runtime
        "scrapers.github",
        "scrapers.github_source",
        "scrapers.t3hd0gg",
        # Config editor imported dynamically in _do_configure
        "zelda3_config",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Game Port Installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Game Port Installer",
)

app = BUNDLE(
    coll,
    name="Game Port Installer.app",
    icon=None,          # Set to "AppIcon.icns" when you have one
    bundle_identifier="com.gameportinstaller.app",
    version="0.1.0",
    info_plist={
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # Allow dark mode
        "LSMinimumSystemVersion": "12.0",
        "CFBundleShortVersionString": "0.1.0",
    },
)
