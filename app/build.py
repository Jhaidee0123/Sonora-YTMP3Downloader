#!/usr/bin/env python3
"""
Empaqueta Sonora como app nativa con PyInstaller.

    Mac:      venv/bin/python app/build.py      -> dist/Sonora.app y dist/Sonora-<arq>.dmg
    Windows:  venv\\Scripts\\python app\\build.py  -> dist\\Sonora.exe

Hay que correrlo en cada sistema: PyInstaller no genera el .exe desde Mac.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
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


def make_dmg():
    """Arma un .dmg con la app y un acceso directo a Aplicaciones para arrastrarla."""
    arch = "AppleSilicon" if platform.machine() == "arm64" else "Intel"
    dmg = ROOT / "dist" / f"Sonora-{arch}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        subprocess.run(["ditto", str(ROOT / "dist" / "Sonora.app"), str(stage / "Sonora.app")], check=True)
        (stage / "Aplicaciones").symlink_to("/Applications")
        dmg.unlink(missing_ok=True)
        subprocess.run(
            ["hdiutil", "create", "-volname", "Sonora", "-srcfolder", str(stage),
             "-ov", "-format", "UDZO", str(dmg)],
            check=True,
        )
    print(f"Instalador listo: {dmg}")


if sys.platform == "darwin" and shutil.which("hdiutil"):
    make_dmg()
