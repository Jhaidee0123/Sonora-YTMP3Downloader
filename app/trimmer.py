"""
Recorte visual: forma de onda, servidor local para escuchar el audio dentro
de la ventana y corte final con ffmpeg.
"""

import array
import mimetypes
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

PEAK_RATE = 2000  # muestras por segundo usadas para dibujar la onda

ENCODERS = {
    ".flac": ["-c:a", "flac"],
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
    ".m4a": ["-c:a", "aac", "-b:a", "256k"],
}
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/mp4", ".m4a")


def peaks(path, ffmpeg, buckets=1000):
    """Devuelve (picos 0..1, duracion en segundos) para dibujar la onda."""
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
         "-ar", str(PEAK_RATE), "-f", "s16le", "-"],
        capture_output=True, check=True, creationflags=NO_WINDOW,
    ).stdout
    samples = array.array("h", raw[: len(raw) // 2 * 2])
    duration = len(samples) / PEAK_RATE
    size = max(1, len(samples) // buckets)
    values = [
        max(abs(min(chunk)), abs(max(chunk))) if chunk else 0
        for chunk in (samples[i:i + size] for i in range(0, len(samples), size))
    ]
    top = max(values) or 1
    return [round(v / top, 3) for v in values], duration


def cut(src, dst, start, end, ffmpeg):
    """Corta [start, end] segundos de `src` en `dst`, con el mismo formato."""
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(src), "-map", "0:a:0", *ENCODERS.get(Path(src).suffix.lower(), []),
         str(dst)],
        check=True, creationflags=NO_WINDOW,
    )


class MediaServer:
    """Sirve archivos de audio en 127.0.0.1 para el reproductor de la ventana.

    Soporta peticiones Range: sin ellas el reproductor no puede adelantar."""

    def __init__(self):
        self._files = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = server._files.get(self.path.strip("/").split("?")[0].split(".")[0])
                if not path or not path.exists():
                    self.send_error(404)
                    return
                size = path.stat().st_size
                start, end = 0, size - 1
                header = self.headers.get("Range", "")
                if header.startswith("bytes="):
                    first, _, last = header[6:].split(",")[0].partition("-")
                    if first:
                        start = int(first)
                        end = int(last) if last else end
                    elif last:
                        start = size - int(last)
                    end = min(end, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                length = end - start + 1
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                try:
                    with open(path, "rb") as f:
                        f.seek(start)
                        while length > 0:
                            chunk = f.read(min(length, 256 * 1024))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            length -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # El reproductor cancela peticiones al adelantar

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def url_for(self, path):
        token = secrets.token_urlsafe(12)
        self._files[token] = Path(path)
        return f"http://127.0.0.1:{self._httpd.server_port}/{token}{Path(path).suffix}"

    def shutdown(self):
        self._httpd.shutdown()
