"""
Actualizacion automatica de Sonora desde los Releases de GitHub.

Al abrir la app se consulta la ultima version publicada. Si hay una mas nueva
se descarga el instalador de este sistema y un pequeno script lo reemplaza
cuando la app se cierra, y la vuelve a abrir.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from engine import ARCH, IS_MAC, IS_WIN, NO_WINDOW, _fetch
from version import __version__

REPO = "Jhaidee0123/Sonora-YTMP3Downloader"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

if IS_WIN:
    ASSET = "Sonora.exe"
elif IS_MAC:
    ASSET = "Sonora-AppleSilicon.dmg" if ARCH == "arm64" else "Sonora-Intel.dmg"
else:
    ASSET = None


def _parse(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def installed_path():
    """Ruta del .exe o del .app en ejecucion, o None si se corre desde el codigo."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable)
    return exe.parents[2] if IS_MAC else exe


def check():
    """Devuelve {"version", "url", "notes"} si hay una version nueva, o None."""
    if not ASSET:
        return None
    release = json.loads(_fetch(LATEST_URL))
    latest = release.get("tag_name", "")
    if _parse(latest) <= _parse(__version__):
        return None
    asset = next((a for a in release.get("assets", []) if a["name"] == ASSET), None)
    if not asset:
        return None
    return {
        "version": latest.lstrip("v"),
        "url": asset["browser_download_url"],
        "notes": (release.get("body") or "").strip(),
    }


def install(update):
    """Descarga la actualizacion y deja listo el reemplazo. Despues hay que
    cerrar la app: el script espera a que se cierre, reemplaza y la reabre."""
    target = installed_path()
    if not target:
        raise RuntimeError("Las actualizaciones solo se instalan en la app empaquetada")

    tmp = Path(tempfile.mkdtemp(prefix="sonora-update-"))
    download = tmp / ASSET
    download.write_bytes(_fetch(update["url"]))
    pid = os.getpid()

    if IS_WIN:
        script = tmp / "update.bat"
        script.write_text(
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && '
            "(timeout /t 1 /nobreak >nul & goto wait)\r\n"
            # El .exe puede seguir bloqueado unos instantes tras cerrar: reintentar
            "set n=0\r\n"
            ":move\r\n"
            f'move /y "{download}" "{target}" >nul 2>&1 && goto done\r\n'
            "set /a n+=1\r\n"
            "if %n% lss 30 (timeout /t 1 /nobreak >nul & goto move)\r\n"
            ":done\r\n"
            f'start "" "{target}"\r\n',
            encoding="utf-8",
        )
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    else:
        script = tmp / "update.sh"
        script.write_text(
            "#!/bin/bash\n"
            f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
            f'MNT=$(hdiutil attach -nobrowse -readonly "{download}" | tail -1 | awk -F"\\t" \'{{print $NF}}\')\n'
            f'APP="{target}"\n'
            'rm -rf "$APP.old"\n'
            # Si algo falla se restaura la version anterior
            'if mv "$APP" "$APP.old"; then\n'
            '  if ditto "$MNT/Sonora.app" "$APP"; then rm -rf "$APP.old";\n'
            '  else rm -rf "$APP"; mv "$APP.old" "$APP"; fi\n'
            'fi\n'
            'hdiutil detach -quiet "$MNT"\n'
            'open "$APP"\n'
            f'rm -rf "{tmp}"\n'
        )
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, close_fds=True)
