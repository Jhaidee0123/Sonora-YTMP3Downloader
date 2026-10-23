"""
Motor de Sonora: mantiene yt-dlp y ffmpeg al dia y ejecuta las descargas.

yt-dlp NO va empaquetado dentro de la app: se usa el ejecutable oficial,
guardado en la carpeta de datos del usuario, para poder actualizarlo con
`yt-dlp -U` cada vez que se abre la app.
"""

import io
import json
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import certifi

import tagger
import trimmer
from library import Library, url_key

APP_NAME = "Sonora"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

YTDLP_ASSET = {"win32": "yt-dlp.exe", "darwin": "yt-dlp_macos"}.get(sys.platform, "yt-dlp")
YTDLP_URL = f"https://github.com/yt-dlp/yt-dlp/releases/latest/download/{YTDLP_ASSET}"
FFMPEG_WIN_URL = (
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
# En Mac no hay descarga oficial de ffmpeg: se usa el binario autocontenido
# que publica el paquete imageio-ffmpeg en PyPI (solo depende del sistema).
FFMPEG_MAC_INDEX = "https://pypi.org/pypi/imageio-ffmpeg/json"

ARCH = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
# yt-dlp necesita un runtime de JavaScript (Deno) para extraer bien de YouTube
DENO_TARGET = {
    "win32": "x86_64-pc-windows-msvc",
    "darwin": "aarch64-apple-darwin" if ARCH == "arm64" else "x86_64-apple-darwin",
}.get(sys.platform, f"{'aarch64' if ARCH == 'arm64' else 'x86_64'}-unknown-linux-gnu")
DENO_URL = f"https://github.com/denoland/deno/releases/latest/download/deno-{DENO_TARGET}.zip"

# En Windows evita que cada subproceso abra una consola
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0

# Carpetas donde suele estar instalado ffmpeg/deno. Una .app abierta desde
# Finder no hereda el PATH de la terminal, asi que se agregan a mano.
EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin"] if IS_MAC else []

QUALITIES = {
    # Sin perdida: decodifica la mejor pista disponible (normalmente Opus)
    # a FLAC, sin una segunda compresion. Compatible con rekordbox y Serato.
    "flac": ["-f", "bestaudio/best", "-x", "--audio-format", "flac"],
    "mp3": ["-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "320K"],
    # AAC tal como lo entrega YouTube, sin recodificar
    "m4a": ["-f", "bestaudio[ext=m4a]/bestaudio/best", "-x", "--audio-format", "m4a"],
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
META_FIELDS = (
    ".{extractor_key,id,title,uploader,artist,track,album,release_year,"
    "duration,thumbnail,webpage_url,playlist_index}"
)
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def data_dir():
    """Carpeta de datos de la app segun el sistema operativo."""
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


BIN_DIR = data_dir() / "bin"
EXE = ".exe" if IS_WIN else ""
YTDLP_PATH = BIN_DIR / f"yt-dlp{EXE}"
# Canciones descargadas para recortar: se borran al cerrar la app
TRIM_DIR = data_dir() / "trim"
DENO_PATH = BIN_DIR / f"deno{EXE}"


def parse_urls(text):
    """Extrae URLs unicas de un texto, en el orden en que aparecen."""
    seen = []
    for url in URL_RE.findall(text or ""):
        url = url.rstrip(".,;)")
        if url not in seen:
            seen.append(url)
    return seen


def _env():
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(EXTRA_PATHS + [str(BIN_DIR), env.get("PATH", "")])
    return env


def _fetch(url):
    """Descarga una URL a memoria usando los certificados de certifi."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        return resp.read()


def _run(args, timeout=180):
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=_env(), creationflags=NO_WINDOW,
    )


def _install(path, data):
    """Guarda un ejecutable de forma atomica (sin dejar archivos a medias)."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.chmod(tmp.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    tmp.replace(path)


def _from_zip(zip_bytes, match):
    """Devuelve el contenido del primer archivo del zip cuyo nombre cumpla `match`."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for name in archive.namelist():
            if match(name.rsplit("/", 1)[-1]):
                return archive.read(name)
    raise RuntimeError("El archivo descargado no contiene el ejecutable esperado")


def ensure_ytdlp():
    """Descarga el ejecutable de yt-dlp si todavia no existe."""
    if not YTDLP_PATH.exists():
        _install(YTDLP_PATH, _fetch(YTDLP_URL))


def find_deno():
    if DENO_PATH.exists():
        return DENO_PATH
    found = shutil.which("deno", path=_env()["PATH"])
    return Path(found) if found else None


def ensure_deno():
    """Busca Deno; si no esta instalado lo descarga."""
    found = find_deno()
    if found:
        return found
    _install(DENO_PATH, _from_zip(_fetch(DENO_URL), lambda n: n == DENO_PATH.name))
    return DENO_PATH


def update_deno():
    """Actualiza el Deno propio de la app una vez al mes (el del sistema no se toca)."""
    if not DENO_PATH.exists() or time.time() - DENO_PATH.stat().st_mtime < 30 * 86400:
        return
    try:
        _run([str(DENO_PATH), "upgrade", "--quiet"], timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return
    DENO_PATH.touch()


def ytdlp_version():
    result = _run([str(YTDLP_PATH), "--version"], timeout=60)
    return result.stdout.strip() or None


def update_ytdlp():
    """Actualiza yt-dlp a la ultima version. Devuelve la version instalada."""
    try:
        _run([str(YTDLP_PATH), "-U"])
    except (OSError, subprocess.TimeoutExpired):
        pass  # Sin internet: se sigue con la version que ya hay
    return ytdlp_version()


def find_ffmpeg():
    """Devuelve la carpeta que contiene ffmpeg, o None si no se encuentra."""
    exe = "ffmpeg.exe" if IS_WIN else "ffmpeg"
    candidates = [BIN_DIR]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "ffmpeg")
    candidates += [Path(p) for p in EXTRA_PATHS]
    for folder in candidates:
        if (folder / exe).exists():
            return folder
    found = shutil.which("ffmpeg")
    return Path(found).parent if found else None


def ensure_ffmpeg():
    """Busca ffmpeg; si no esta instalado lo descarga."""
    folder = find_ffmpeg()
    if folder:
        return folder

    if IS_WIN:
        data = _fetch(FFMPEG_WIN_URL)
        for exe in ("ffprobe.exe", "ffmpeg.exe"):
            _install(BIN_DIR / exe, _from_zip(data, lambda n, exe=exe: n == exe))
    elif IS_MAC:
        files = json.loads(_fetch(FFMPEG_MAC_INDEX))["urls"]
        tag = "arm64" if ARCH == "arm64" else "x86_64"
        wheel = next(f["url"] for f in files if "macosx" in f["filename"] and tag in f["filename"])
        _install(BIN_DIR / "ffmpeg", _from_zip(_fetch(wheel), lambda n: n.startswith("ffmpeg-")))
    else:
        raise RuntimeError("No se encontró ffmpeg. Instálalo con el gestor de paquetes del sistema")
    return BIN_DIR


class Engine:
    """Prepara las herramientas y ejecuta descargas reportando eventos."""

    def __init__(self, emit):
        self.emit = emit
        self.ready = threading.Event()
        self.error = None
        self.version = None
        self.ffmpeg_dir = None
        self.deno_path = None
        self.library = Library(data_dir() / "library.json")
        self.sources = {}
        shutil.rmtree(TRIM_DIR, ignore_errors=True)  # restos de una sesion anterior
        self._update_lock = threading.Lock()
        self._procs = set()

    def setup(self):
        """Instala/actualiza yt-dlp, ffmpeg y Deno. Corre en un hilo aparte."""
        try:
            missing = not (YTDLP_PATH.exists() and find_ffmpeg() and find_deno())
            self.emit({"type": "engine", "state": "installing" if missing else "updating"})
            ensure_ytdlp()
            self.ffmpeg_dir = ensure_ffmpeg()
            self.deno_path = ensure_deno()
            self.version = update_ytdlp()
            update_deno()
            self.emit({"type": "engine", "state": "ready", "version": self.version})
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.emit({"type": "engine", "state": "error", "message": self.error})
        finally:
            self.ready.set()

    def force_update(self):
        """Actualiza yt-dlp (una sola vez aunque lo pidan varias descargas)."""
        if not self._update_lock.acquire(blocking=False):
            with self._update_lock:
                return
        try:
            self.emit({"type": "engine", "state": "updating"})
            self.version = update_ytdlp()
            self.emit({"type": "engine", "state": "ready", "version": self.version})
        finally:
            self._update_lock.release()

    def download(self, job_id, url, quality, out_dir, force=False, trim=False):
        """Descarga una URL. Con `trim` la cancion completa queda aparte, lista
        para recortarla en la app, y solo se guarda lo que se recorte."""
        self.ready.wait()
        if self.error:
            self.emit({"type": "job", "id": job_id, "state": "error", "message": self.error})
            return

        existing = None if force else self.library.find(url_key(url), quality, None)
        if existing and trim:
            # Ya la tenias completa: se recorta desde ese archivo, sin descargar
            self._register(job_id, existing, quality, out_dir, {url_key(url)}, temp=False)
            self.emit({"type": "job", "id": job_id, "state": "trim_ready", "path": existing})
            return
        if existing:
            self._register(job_id, existing, quality, out_dir, {url_key(url)}, temp=False)
            self.emit({"type": "job", "id": job_id, "state": "duplicate", "path": existing})
            return

        args = (job_id, url, quality, out_dir, force, trim)
        errors = self._run_download(*args)
        if errors and any("403" in e or "Forbidden" in e for e in errors):
            # YouTube suele bloquear versiones viejas: actualizar y reintentar
            self.emit({"type": "job", "id": job_id, "state": "retrying"})
            self.force_update()
            errors = self._run_download(*args)
        if errors:
            self.emit({"type": "job", "id": job_id, "state": "error", "message": errors[-1]})

    def _run_download(self, job_id, *args):
        """Ejecuta yt-dlp. Devuelve la lista de errores ([] si todo salio bien)."""
        staging = data_dir() / "staging" / job_id
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            return self._download_to(staging, job_id, *args)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _download_to(self, staging, job_id, url, quality, out_dir, force, trim):
        cmd = [
            str(YTDLP_PATH), url,
            "--no-playlist", "--newline", "--progress", "--no-colors",
            "--ffmpeg-location", str(self.ffmpeg_dir),
            "--js-runtimes", f"deno:{self.deno_path}",
            *QUALITIES.get(quality, QUALITIES["flac"]),
            # La miniatura queda como respaldo si no aparece la caratula oficial
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "-o", str(staging / "%(id)s.%(ext)s"),
            "--print", f"before_dl:META %({META_FIELDS})j",
            "--print", "after_move:FILE %(filepath)s",
            "--progress-template",
            "download:PROG %(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        ]
        self.emit({"type": "job", "id": job_id, "state": "starting"})

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                env=_env(), creationflags=NO_WINDOW,
            )
        except OSError as e:
            return [str(e)]

        self._procs.add(proc)
        errors, done, meta = [], [], None
        for raw in proc.stdout:
            line = ANSI_RE.sub("", raw).strip()
            if line.startswith("META "):
                try:
                    meta = json.loads(line[5:])
                except ValueError:
                    continue
                self.emit({"type": "job", "id": job_id, "state": "downloading", "meta": meta})
                key = f"{meta['extractor_key']}:{meta['id']}"
                existing = None if force or meta.get("playlist_index") else self.library.find(
                    key, quality, None)
                if existing:
                    proc.kill()
                    proc.wait()
                    self._procs.discard(proc)
                    self._register(job_id, existing, quality, out_dir, {key}, temp=False)
                    state = "trim_ready" if trim else "duplicate"
                    self.emit({"type": "job", "id": job_id, "state": state, "path": existing})
                    return []
            elif line.startswith("PROG "):
                pct, speed, eta = (line[5:].split("|") + ["", ""])[:3]
                try:
                    percent = float(pct.strip().rstrip("%"))
                except ValueError:
                    continue
                self.emit({
                    "type": "job", "id": job_id, "state": "downloading",
                    "percent": percent, "speed": speed.strip(), "eta": eta.strip(),
                })
                if percent >= 100:
                    self.emit({"type": "job", "id": job_id, "state": "converting"})
            elif line.startswith("FILE ") and meta:
                done.append((meta, Path(line[5:])))
            elif line.startswith("ERROR:"):
                errors.append(line[6:].strip())

        proc.wait()
        self._procs.discard(proc)
        if proc.returncode != 0 or not done:
            return errors or [f"yt-dlp terminó con código {proc.returncode}"]

        self.emit({"type": "job", "id": job_id, "state": "tagging"})
        if trim and len(done) == 1:
            meta, staged = done[0]
            info = self._tag(meta, staged, url)
            holder = TRIM_DIR / job_id
            holder.mkdir(parents=True, exist_ok=True)
            source = holder / tagger.filename(info, staged.suffix.lstrip("."))
            shutil.move(str(staged), source)
            keys = {url_key(url), f"{meta['extractor_key']}:{meta['id']}"}
            self._register(job_id, source, quality, out_dir, keys, temp=True)
            self.emit({"type": "job", "id": job_id, "state": "trim_ready",
                       "path": str(source), "info": _public(info)})
            return []

        result = None
        for item_meta, staged in done:
            result = self._finish(item_meta, staged, url, quality, out_dir, force)
        self._register(job_id, result["path"], quality, out_dir, result["keys"], temp=False)
        if len(done) == 1 and result["duplicate"]:
            # Ya existia un archivo con ese nombre en la carpeta
            self.emit({"type": "job", "id": job_id, "state": "duplicate", "path": result["path"]})
        else:
            self.emit({"type": "job", "id": job_id, "state": "done", "count": len(done),
                       "path": result["path"], "info": result["info"]})
        return []

    def _tag(self, meta, staged, url):
        """Limpia el titulo, busca la caratula y escribe las etiquetas en el archivo."""
        try:
            info = tagger.resolve(meta)
        except Exception:  # noqa: BLE001 - sin datos oficiales se usa lo adivinado
            info = tagger.guess(meta)

        cover = None
        if info.get("cover_url"):
            try:
                cover = _fetch(info["cover_url"])
            except Exception:  # noqa: BLE001
                info.pop("cover_url")
        thumb = staged.with_suffix(".jpg")
        if cover is None and thumb.exists():
            try:
                cover = tagger.square_thumbnail(thumb, self.ffmpeg)
            except (OSError, subprocess.CalledProcessError):
                cover = None
        try:
            tagger.write_tags(staged, info, cover, meta.get("webpage_url") or url)
        except Exception:  # noqa: BLE001 - un error de etiquetas no debe perder la cancion
            pass
        return info

    def _finish(self, meta, staged, url, quality, out_dir, force):
        """Etiqueta el archivo y lo mueve a la carpeta final con un nombre limpio."""
        info = self._tag(meta, staged, url)
        dest = Path(out_dir) / tagger.filename(info, staged.suffix.lstrip("."))
        duplicate = dest.exists() and not force
        if duplicate:
            staged.unlink()
        else:
            dest = _place(staged, dest, move=True)

        keys = {url_key(url), f"{meta['extractor_key']}:{meta['id']}"}
        self.library.add(keys, quality, None, dest)
        return {"path": str(dest), "duplicate": duplicate, "keys": keys, "info": _public(info)}

    # ------------------------------------------------------------ Recortes

    @property
    def ffmpeg(self):
        return str(self.ffmpeg_dir / f"ffmpeg{EXE}")

    def _register(self, job_id, path, quality, out_dir, keys, temp):
        """Recuerda el archivo de cada tarjeta para poder recortarlo despues."""
        self.sources[job_id] = {
            "path": Path(path), "quality": quality, "out_dir": out_dir,
            "keys": keys, "temp": temp,
        }

    def source(self, job_id):
        return self.sources.get(job_id)

    def save_cut(self, job_id, start, end):
        """Guarda el fragmento [start, end] como un archivo nuevo en la carpeta."""
        src = self.sources[job_id]
        start, end = round(float(start), 2), round(float(end), 2)
        name = tagger.section_name(src["path"].stem, start, end, src["path"].suffix)
        tmp = TRIM_DIR / f"{job_id}-cut{src['path'].suffix}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        trimmer.cut(src["path"], tmp, start, end, self.ffmpeg)
        try:
            tagger.copy_tags(src["path"], tmp)
        except Exception:  # noqa: BLE001
            pass
        dest = _place(tmp, Path(src["out_dir"]) / name, move=True)
        self.library.add(src["keys"], src["quality"], (start, end), dest)
        return str(dest)

    def save_full(self, job_id):
        """Guarda tambien la cancion completa de una descarga hecha para recortar."""
        src = self.sources[job_id]
        if not src["temp"]:
            return str(src["path"])
        dest = _place(src["path"], Path(src["out_dir"]) / src["path"].name, move=False)
        self.library.add(src["keys"], src["quality"], None, dest)
        return str(dest)

    def shutdown(self):
        for proc in list(self._procs):
            proc.kill()
        shutil.rmtree(TRIM_DIR, ignore_errors=True)


def _public(info):
    return {k: info.get(k) for k in ("artist", "title", "album", "year", "cover_url")}


def _place(src, dest, move):
    """Mueve/copia `src` a `dest` sin pisar archivos: agrega (2), (3)..."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    base, n = dest, 2
    while dest.exists():
        dest = base.with_name(f"{base.stem} ({n}){base.suffix}")
        n += 1
    (shutil.move if move else shutil.copy2)(str(src), dest)
    return dest
