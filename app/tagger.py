"""
Metadatos de Sonora: limpia titulos, busca la caratula oficial y escribe
las etiquetas (titulo, artista, album, ano, genero, caratula) en el archivo.

Fuentes de caratula, en orden: iTunes, Deezer y, si no hay coincidencia
segura, la miniatura del video recortada a cuadrado.
"""

import json
import re
import ssl
import subprocess
import unicodedata
import urllib.parse
import urllib.request

import certifi
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

# Palabras que delatan "ruido" dentro de parentesis/corchetes del titulo
NOISE_WORDS = {
    "video", "vídeo", "videoclip", "clip", "oficial", "official", "audio",
    "letra", "lyrics", "lyric", "visualizer", "visualiser", "hd", "hq", "4k",
    "1080p", "720p", "new", "nuevo", "estreno", "premiere", "exclusive",
    "exclusivo",
}
# Versiones de una cancion: al buscar la caratula tienen que coincidir,
# para no confundir "Gasolina (Remix)" con "Gasolina"
VERSION_WORDS = {
    "remix", "mix", "edit", "live", "vivo", "acoustic", "acustico",
    "instrumental", "extended", "bootleg", "vip", "sped", "slowed", "dub",
    "rework", "cover", "acapella",
}
# Si aparecen, el parentesis es parte del nombre de la cancion y se conserva
KEEP_WORDS = VERSION_WORDS | {
    "version", "versión", "acústico", "feat", "feat.", "ft", "ft.",
    "prod", "prod.", "remaster", "remastered", "remasterizado",
}
SMALL_WORDS = {"de", "del", "la", "las", "el", "y", "e", "en", "a", "o", "of", "the", "and", "in", "on", "to", "for"}
ACRONYMS = {"DJ", "MC", "UK", "US", "USA", "NY", "LA", "TV", "EP", "LP", "VS", "OG", "II", "III", "IV", "R&B"}
IGNORED_TOKENS = {"remastered", "remaster", "remasterizado", "version", "single"}
BRACKETS_RE = re.compile(r"\s*[\(\[\{]([^\(\)\[\]\{\}]*)[\)\]\}]")
PIPE_RE = re.compile(r"\s*(?:\|+|//)\s*")
ARTIST_SEP_RE = re.compile(r"\s+[-–—~]\s+")
UPLOADER_NOISE_RE = re.compile(r"\s*(?:-\s*topic|vevo|official|oficial|tv)\s*$", re.IGNORECASE)
FILENAME_BAD_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---------------------------------------------------------------- Limpieza

def _words(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return set(re.findall(r"[a-z0-9.]+", "".join(c for c in text if not unicodedata.combining(c))))


def _strip_noise(text):
    """Quita parentesis como (Video Oficial) o [NEW], pero no (Remix) ni (feat. X)."""
    def drop(match):
        words = _words(match.group(1))
        if not words or (words & NOISE_WORDS and not words & KEEP_WORDS):
            return ""
        return match.group(0)

    text = BRACKETS_RE.sub(drop, text)
    return re.sub(r"\s{2,}", " ", text).strip(" -–—~")


def _cap_word(word, first):
    if word.strip("()[]") in ACRONYMS:
        return word
    word = word.lower()
    if not first and word in SMALL_WORDS:
        return word
    for i, c in enumerate(word):
        if c.isalpha():
            return word[:i] + c.upper() + word[i + 1:]
    return word


def smart_case(text):
    """'YA NO MÁS GUARO' -> 'Ya No Más Guaro'. Solo actua si la mayoria del
    texto esta en mayusculas, y solo sobre las palabras en mayusculas."""
    words = text.split(" ")
    shouting = [w for w in words if sum(c.isalpha() for c in w) >= 2 and w.upper() == w]
    lettered = [w for w in words if any(c.isalpha() for c in w)]
    if not lettered or len(shouting) * 2 < len(lettered):
        return text
    return " ".join(
        _cap_word(w, i == 0) if w in shouting else w for i, w in enumerate(words)
    )


def guess(meta):
    """Deduce artista y titulo limpios a partir de los datos de yt-dlp.

    `weak` indica que el artista salio del nombre del canal (poco fiable)."""
    source = meta.get("extractor_key", "")
    title = (meta.get("track") or meta.get("title") or "").replace("｜", "|")
    artist, weak = None, False

    if source == "Bandcamp" and meta.get("artist"):
        artist = meta["artist"]
        if title.startswith(f"{artist} - "):
            title = title[len(artist) + 3:]

    # "Cancion | Letra" -> se descarta lo de despues del "|"
    # "Shakira || Bzrp Music Sessions" -> sin guion, el "|" separa artista y titulo
    pieces = [p for p in PIPE_RE.split(title) if p.strip()] or [title]
    title = pieces[0]
    if (not artist and len(pieces) > 1 and not ARTIST_SEP_RE.search(title)
            and not _words(pieces[1]) & NOISE_WORDS):
        artist, title = title, pieces[1]

    title = _strip_noise(title)
    if not artist:
        parts = ARTIST_SEP_RE.split(title, maxsplit=1)
        if len(parts) == 2:
            artist, title = parts
        elif source != "Mixcloud" and meta.get("artist"):
            artist = meta["artist"]
        else:
            artist = UPLOADER_NOISE_RE.sub("", meta.get("uploader") or "").strip()
            weak = True

    return {
        "artist": _strip_noise(artist or "") or "Desconocido",
        "title": title or meta.get("title") or "Sin título",
        "album": meta.get("album"),
        "year": meta.get("release_year"),
        "weak": weak,
    }


def resolve(meta):
    """Titulo, artista, album, ano, genero y URL de caratula definitivos."""
    info = guess(meta)
    found = lookup(meta, info)
    info.update({k: v for k, v in found.items() if v})
    info["artist"] = smart_case(info["artist"])
    info["title"] = smart_case(info["title"])
    return info


def filename(info, ext):
    name = FILENAME_BAD_RE.sub("", f"{info['artist']} - {info['title']}").strip(". ")
    return f"{name[:180]}.{ext}"


def _clock(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


# ---------------------------------------------------------------- Busqueda

def _fetch(url, timeout=15):
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"User-Agent": "Sonora"})
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return resp.read()


def _norm_tokens(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b(feat|ft|featuring|with|con|and|y)\b\.?", " ", text)
    return {t for t in re.findall(r"[a-z0-9]+", text) if len(t) > 1 or t.isdigit()}


def _coverage(needle, haystack):
    """Fraccion de las palabras de `needle` que aparecen en `haystack`."""
    return len(needle & haystack) / len(needle) if needle else 0.0


def _is_match(cand_artist, cand_title, cand_secs, want):
    """Una coincidencia es segura si TODO el titulo y la mitad del artista
    aparecen en el texto original, es la misma version (remix, en vivo...)
    y la duracion es parecida."""
    # Todo el titulo, incluidos los parentesis ("Bhangra Remix", "feat. X"),
    # tiene que estar en el original. Se ignoran "Remastered" y los anos.
    title_tokens = {t for t in _norm_tokens(cand_title) if not (len(t) == 4 and t.isdigit())}
    if _coverage(title_tokens - IGNORED_TOKENS, want["context"]) < 1.0:
        return False
    if _coverage(_norm_tokens(cand_artist), want["context"]) < 0.5:
        return False
    if _words(cand_title) & VERSION_WORDS != want["versions"]:
        return False
    duration = want["duration"]
    return not (duration and cand_secs and abs(duration - cand_secs) > 45)


def _itunes(term, want):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "entity": "song", "limit": 10}
    )
    for r in json.loads(_fetch(url)).get("results", []):
        secs = (r.get("trackTimeMillis") or 0) / 1000
        if _is_match(r["artistName"], r["trackName"], secs, want):
            return {
                "artist": r["artistName"],
                "title": r["trackName"],
                "album": r.get("collectionName"),
                "year": (r.get("releaseDate") or "")[:4] or None,
                "genre": r.get("primaryGenreName"),
                "cover_url": r["artworkUrl100"].replace("100x100bb", "1000x1000bb"),
            }
    return None


def _deezer(term, want):
    url = "https://api.deezer.com/search?" + urllib.parse.urlencode({"q": term, "limit": 10})
    for r in json.loads(_fetch(url)).get("data", []):
        if _is_match(r["artist"]["name"], r["title"], r.get("duration"), want):
            # Deezer solo da el artista principal: se conserva el nombre propio
            return {
                "album": r["album"]["title"],
                "cover_url": r["album"]["cover_xl"],
            }
    return None


def lookup(meta, info):
    """Busca datos oficiales. Devuelve un dict parcial (puede ir vacio)."""
    if meta.get("extractor_key") in ("Bandcamp", "Mixcloud"):
        return {}  # Bandcamp ya trae datos oficiales; Mixcloud son sesiones
    want = {
        "context": _norm_tokens(" ".join(filter(None, [
            meta.get("title"), meta.get("uploader"), meta.get("artist"), meta.get("track"),
        ]))),
        "versions": _words(info["title"]) & VERSION_WORDS,
        "duration": meta.get("duration"),
    }
    # Si el "artista" es solo el nombre del canal, mejor buscar por el titulo
    term = info["title"] if info["weak"] else f"{info['artist']} {info['title']}"
    for source in (_itunes, _deezer):
        try:
            found = source(term, want)
        except Exception:  # noqa: BLE001 - sin internet o API caida: se sigue
            found = None
        if found:
            return found
    return {}


def square_thumbnail(path, ffmpeg):
    """Recorta la miniatura a cuadrado (sin franjas negras) y la devuelve en JPG."""
    probe = subprocess.run(
        [ffmpeg, "-i", str(path)], capture_output=True, text=True, errors="replace"
    ).stderr
    size = re.search(r", (\d{2,5})x(\d{2,5})", probe)
    if not size:
        return path.read_bytes()
    w, h = int(size.group(1)), int(size.group(2))
    # Miniaturas 4:3 de YouTube: el video 16:9 va en el centro con franjas
    content_h = round(w * 9 / 16) if abs(w / h - 4 / 3) < 0.05 else h
    side = min(w, content_h)
    out = path.with_name(path.stem + ".square.jpg")
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(path), "-vf",
         f"crop={side}:{side}:{(w - side) // 2}:{(h - side) // 2},scale='min(800,iw)':-2",
         str(out)],
        check=True,
    )
    return out.read_bytes()


# ---------------------------------------------------------------- Etiquetas

def write_tags(path, info, cover, source_url):
    """Escribe las etiquetas en FLAC, MP3 o M4A, reemplazando las anteriores."""
    ext = path.suffix.lower()
    year = str(info.get("year") or "")

    if ext == ".mp3":
        try:
            tags = ID3(path)
            tags.delete()
        except ID3NoHeaderError:
            pass
        tags = ID3()
        tags.add(TIT2(encoding=3, text=info["title"]))
        tags.add(TPE1(encoding=3, text=info["artist"]))
        if info.get("album"):
            tags.add(TALB(encoding=3, text=info["album"]))
        if year:
            tags.add(TDRC(encoding=3, text=year))
        if info.get("genre"):
            tags.add(TCON(encoding=3, text=info["genre"]))
        tags.add(COMM(encoding=3, lang="spa", desc="", text=source_url))
        if cover:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
        # ID3 v2.3: la version que mejor leen rekordbox, Serato y Windows
        tags.save(path, v2_version=3)

    elif ext == ".flac":
        audio = FLAC(path)
        audio.delete()
        audio.clear_pictures()
        audio["title"] = info["title"]
        audio["artist"] = info["artist"]
        if info.get("album"):
            audio["album"] = info["album"]
        if year:
            audio["date"] = year
        if info.get("genre"):
            audio["genre"] = info["genre"]
        audio["comment"] = source_url
        if cover:
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, "image/jpeg", cover
            audio.add_picture(pic)
        audio.save()

    elif ext in (".m4a", ".mp4"):
        audio = MP4(path)
        audio.delete()
        audio["\xa9nam"] = info["title"]
        audio["\xa9ART"] = info["artist"]
        if info.get("album"):
            audio["\xa9alb"] = info["album"]
        if year:
            audio["\xa9day"] = year
        if info.get("genre"):
            audio["\xa9gen"] = info["genre"]
        audio["\xa9cmt"] = source_url
        if cover:
            audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()


def copy_tags(src, dst):
    """Copia etiquetas y caratula de `src` a `dst` (mismo formato), para los recortes."""
    ext = src.suffix.lower()
    if ext == ".mp3":
        try:
            ID3(src).save(dst, v2_version=3)
        except ID3NoHeaderError:
            pass
    elif ext == ".flac":
        source, target = FLAC(src), FLAC(dst)
        target.delete()
        for key, values in (source.tags or {}).items():
            target[key] = values
        for pic in source.pictures:
            target.add_picture(pic)
        target.save()
    elif ext in (".m4a", ".mp4"):
        source, target = MP4(src), MP4(dst)
        target.delete()
        for key, values in (source.tags or {}).items():
            target[key] = values
        target.save()


def section_name(stem, start, end, ext):
    """'Artista - Cancion [1m20s-4m10s].flac'"""
    return f"{stem} [{_clock(start)}-{_clock(end)}]{ext}"
