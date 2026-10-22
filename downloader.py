#!/usr/bin/env python3
"""
YTMp3Downloader - Descarga canciones de YouTube como MP3.

Uso:
    python3 downloader.py                  # Lee links de songs.txt
    python3 downloader.py mi_lista.txt     # Lee links de un archivo custom
    python3 downloader.py -o ~/Music       # Cambia la carpeta de destino
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def check_ffmpeg():
    """Verifica si ffmpeg esta instalado."""
    if shutil.which("ffmpeg"):
        return True
    print("=" * 60)
    print("  ffmpeg NO esta instalado.")
    print("  Es necesario para convertir audio a MP3.")
    print()
    print("  Instalar con Homebrew:")
    print("    brew install ffmpeg")
    print("=" * 60)
    return False


def check_yt_dlp():
    """Verifica si yt-dlp esta instalado."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def load_urls(filepath):
    """Lee URLs de un archivo de texto, ignorando comentarios y lineas vacias."""
    path = Path(filepath)
    if not path.exists():
        print(f"Error: No se encontro el archivo '{filepath}'")
        sys.exit(1)

    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)

    return urls


def download_songs(urls, output_dir):
    """Descarga una lista de URLs como MP3."""
    import yt_dlp

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        # Links con &list=RD... descargan solo el video, no el mix completo
        "noplaylist": True,
        "ignoreerrors": True,
        "no_warnings": False,
        "quiet": False,
    }

    total = len(urls)
    ok = 0
    failed = []

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{total}] Descargando: {url}")
        print("-" * 50)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            ok += 1
        except Exception as e:
            print(f"  Error: {e}")
            failed.append(url)

    # Resumen
    print("\n" + "=" * 50)
    print(f"  Completado: {ok}/{total} canciones descargadas")
    print(f"  Destino: {output_dir.resolve()}")
    if failed:
        print(f"\n  Fallaron ({len(failed)}):")
        for url in failed:
            print(f"    - {url}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Descarga canciones de YouTube como MP3")
    parser.add_argument(
        "file",
        nargs="?",
        default="songs.txt",
        help="Archivo con links de YouTube, uno por linea (default: songs.txt)",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Carpeta de destino (default: downloads/)",
    )
    args = parser.parse_args()

    # Verificar dependencias
    if not check_ffmpeg():
        sys.exit(1)

    if not check_yt_dlp():
        print("yt-dlp no esta instalado. Ejecuta:")
        print("  pip3 install -r requirements.txt")
        sys.exit(1)

    # Cargar URLs
    urls = load_urls(args.file)
    if not urls:
        print(f"No se encontraron links en '{args.file}'")
        print("Agrega links de YouTube al archivo, uno por linea.")
        sys.exit(0)

    print(f"Se encontraron {len(urls)} links en '{args.file}'")
    print(f"Destino: {Path(args.output).resolve()}")
    print()

    download_songs(urls, args.output)


if __name__ == "__main__":
    main()
