# Sonora: ideas para el futuro

Funciones pensadas pero todavía no implementadas, en el orden sugerido.

## 1. Listas de reproducción de YouTube con selección

Hoy la app ignora el `&list=` a propósito y baja solo la canción. La idea es que al pegar
una lista (o un mix `RD...`) se muestren todas las canciones con su miniatura y casillas
para elegir cuáles descargar, en vez de bajarlas todas.

- yt-dlp ya extrae listas: `--flat-playlist -J` devuelve los títulos sin descargar nada.
- Cada canción elegida sería una tarjeta normal de la cola (con limpieza de título,
  carátula y control de duplicados).
- Lo mismo serviría para sets de SoundCloud y álbumes de Bandcamp, que hoy se bajan
  completos en una sola tarjeta.

## 2. Importar playlists de Spotify (y Apple Music, Deezer, Tidal)

Spotify no permite bajar audio, solo la lista de canciones. Por cada "Artista – Canción"
se buscaría el audio en YouTube y se elegiría la mejor coincidencia.

- **Leer la playlist:** con la API de Spotify hace falta registrar una app gratuita en
  Spotify Developer (Client ID/Secret). Desde 2024 las playlists editoriales
  ("Today's Top Hits") y las algorítmicas ("Descubrimiento semanal") pueden no estar
  disponibles para apps nuevas. Alternativa sin registro: leer la página pública
  `open.spotify.com/embed/playlist/<id>`, más frágil.
- **Elegir el video correcto:** buscar `ytsearch5:"artista canción"`, preferir audio
  oficial o canales "- Topic", comparar la duración con la de Spotify (±5 s) y descartar
  versiones en vivo, covers o remixes que no estén en el nombre original. Se puede
  reutilizar la lógica de `tagger._is_match`.
- Los metadatos (álbum, año, carátula) vendrían directamente de Spotify.

## 3. Buscador dentro de la app

Escribir "coqueta fuerza regida" y elegir entre los resultados (miniatura, canal,
duración) sin tener que copiar el link. Usa la misma búsqueda que la importación de
Spotify, así que conviene hacerlas juntas.

## 4. Exportar playlists a rekordbox y Serato

Cada playlist descargada en su propia carpeta, con un archivo `.m3u8` en el mismo orden,
que rekordbox y Serato importan tal cual. Para rekordbox también se puede generar su XML
de colección.

## 5. Sincronizar playlists

"Seguir" una playlist (de YouTube o Spotify): cada vez que se abre la app baja solo las
canciones nuevas. Requiere los puntos 1 o 2 y guardar qué playlists se siguen.

## 6. Separar stems (voz, batería, bajo, resto)

Con Demucs (modelo de IA, funciona sin internet) para hacer acapellas e instrumentales.

- Pesa unos 2 GB (PyTorch + modelo): convendría descargarlo solo si se activa la función.
- En CPU tarda varios minutos por canción (en la i9 unos 3–5 min).

## Descartado por ahora

- **Detección de BPM y tonalidad:** rekordbox y Serato ya lo hacen al analizar, y mejor.
