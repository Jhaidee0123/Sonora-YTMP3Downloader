"""
Registro de lo que ya se descargo, para no repetir descargas.

Cada cancion se guarda con dos claves: la de la plataforma ("Youtube:abc123")
y la URL que se pego. Una entrada solo cuenta si el archivo todavia existe:
si lo borraste, se puede volver a descargar.
"""

import json
import re
import threading
from pathlib import Path

YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|music\.youtube\.com/watch\?v=)([\w-]{11})")


def url_key(url):
    """Clave a partir de la URL. YouTube se reconoce por el id del video."""
    match = YOUTUBE_ID_RE.search(url)
    if match:
        return f"Youtube:{match.group(1)}"
    return "url:" + url.split("?")[0].rstrip("/").lower()


def variant(quality, section):
    """FLAC y MP3 de la misma cancion, o un recorte, cuentan como distintos."""
    cut = f"{section[0]}-{section[1] or ''}" if section else "full"
    return f"{quality}|{cut}"


class Library:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            self._items = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self._items = {}

    def find(self, key, quality, section):
        """Devuelve la ruta si esa cancion ya esta descargada y el archivo existe."""
        with self._lock:
            entry = self._items.get(f"{key}|{variant(quality, section)}")
        if entry and Path(entry["path"]).exists():
            return entry["path"]
        return None

    def add(self, keys, quality, section, path):
        with self._lock:
            for key in keys:
                self._items[f"{key}|{variant(quality, section)}"] = {"path": str(path)}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._items, ensure_ascii=False, indent=1))
            tmp.replace(self.path)
