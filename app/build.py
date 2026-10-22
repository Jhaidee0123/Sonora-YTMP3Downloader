#!/usr/bin/env python3
"""
Empaqueta Sonora como app nativa con PyInstaller.

    Mac:      venv/bin/python app/build.py      -> dist/Sonora.app
    Windows:  venv\\Scripts\\python app\\build.py  -> dist\\Sonora.exe

Hay que correrlo en cada sistema: PyInstaller no genera el .exe desde Mac.
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

HERE = Path(__file__).parent
ROOT = HERE.parent

args = [
    str(HERE / "main.py"),
    "--name", "Sonora",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--paths", str(HERE),
    "--add-data", f"{HERE / 'ui'}{os.pathsep}ui",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]

if sys.platform == "darwin":
    args += ["--icon", str(HERE / "icon.icns"), "--osx-bundle-identifier", "com.sonora.app"]
else:
    # Windows: un solo .exe facil de copiar (PyInstaller convierte el .png a .ico con Pillow)
    args += ["--icon", str(HERE / "icon.png"), "--onefile"]

PyInstaller.__main__.run(args)
