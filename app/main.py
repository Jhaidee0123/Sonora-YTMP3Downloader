#!/usr/bin/env python3
"""
Sonora - App de escritorio para descargar audio de YouTube.

Uso en desarrollo:
    venv/bin/python app/main.py
"""

import json
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import webview

from engine import APP_NAME, IS_MAC, IS_WIN, QUALITIES, Engine, data_dir, parse_urls

SETTINGS_PATH = data_dir() / "settings.json"
DEFAULT_SETTINGS = {
    "out_dir": str(Path.home() / "Music" / APP_NAME),
    "quality": "flac",
}
MAX_PARALLEL = 3


def resource_dir():
    """Carpeta de recursos, tanto en desarrollo como dentro de la app empaquetada."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def load_settings():
    try:
        saved = json.loads(SETTINGS_PATH.read_text())
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULT_SETTINGS, **saved}


class Api:
    """Metodos expuestos al JavaScript de la interfaz (window.pywebview.api)."""

    def __init__(self):
        # Los atributos con "_" no se exponen a JavaScript
        self._window = None
        self._settings = load_settings()
        self._engine = Engine(self._emit)
        self._pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL)
        self._jobs = {}

    def _emit(self, event):
        if self._window:
            self._window.evaluate_js(f"window.onEngineEvent({json.dumps(event)})")

    def _save_settings(self):
        SETTINGS_PATH.write_text(json.dumps(self._settings, indent=2))

    def init(self):
        """La interfaz lo llama al cargar: arranca la preparacion del motor."""
        threading.Thread(target=self._engine.setup, daemon=True).start()
        return {"settings": self._settings, "platform": sys.platform}

    def add_urls(self, text):
        jobs = []
        for url in parse_urls(text):
            job_id = uuid.uuid4().hex[:8]
            self._jobs[job_id] = url
            jobs.append({"id": job_id, "url": url})
            self._submit(job_id)
        return jobs

    def retry(self, job_id):
        if job_id in self._jobs:
            self._submit(job_id)

    def _submit(self, job_id):
        self._pool.submit(
            self._engine.download, job_id, self._jobs[job_id],
            self._settings["quality"], self._settings["out_dir"],
        )

    def set_quality(self, quality):
        if quality in QUALITIES:
            self._settings["quality"] = quality
            self._save_settings()

    def choose_folder(self):
        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER, directory=self._settings["out_dir"]
        )
        if result:
            self._settings["out_dir"] = result[0]
            self._save_settings()
        return self._settings["out_dir"]

    def import_txt(self):
        """Lee los links de un archivo .txt elegido por el usuario."""
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Texto (*.txt)", "Todos (*.*)")
        )
        if not result:
            return ""
        return Path(result[0]).read_text(encoding="utf-8", errors="replace")

    def reveal(self, path):
        """Muestra el archivo en Finder / Explorador."""
        if IS_MAC:
            subprocess.Popen(["open", "-R", path])
        elif IS_WIN:
            subprocess.Popen(["explorer", "/select,", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])

    def open_folder(self):
        folder = self._settings["out_dir"]
        Path(folder).mkdir(parents=True, exist_ok=True)
        if IS_MAC:
            subprocess.Popen(["open", folder])
        elif IS_WIN:
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])


def main():
    api = Api()
    window = webview.create_window(
        APP_NAME,
        url=str(resource_dir() / "ui" / "index.html"),
        js_api=api,
        width=820,
        height=720,
        min_size=(560, 560),
        background_color="#0B0B12",
    )
    api._window = window
    window.events.closed += api._engine.shutdown
    webview.start()


if __name__ == "__main__":
    main()
