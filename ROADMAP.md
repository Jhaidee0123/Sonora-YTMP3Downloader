# Sonora: ideas para el futuro

Funciones pensadas pero todavía no implementadas, en el orden sugerido.

## 1. Importar playlists de Spotify (y Apple Music, Deezer, Tidal)

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

## 2. Buscador dentro de la app

Escribir "coqueta fuerza regida" y elegir entre los resultados (miniatura, canal,
duración) sin tener que copiar el link. Usa la misma búsqueda que la importación de
Spotify, así que conviene hacerlas juntas.

## 3. Exportar playlists a rekordbox y Serato

Cada playlist descargada en su propia carpeta, con un archivo `.m3u8` en el mismo orden,
que rekordbox y Serato importan tal cual. Para rekordbox también se puede generar su XML
de colección.

## 4. Sincronizar playlists

"Seguir" una playlist (de YouTube o Spotify): cada vez que se abre la app baja solo las
canciones nuevas. Las de YouTube ya se pueden leer (selector de álbumes y listas);
las de Spotify requieren el punto 1. Falta guardar qué playlists se siguen.

## 5. Separar stems (voz, batería, bajo, resto)

Con Demucs (modelo de IA, funciona sin internet) para hacer acapellas e instrumentales.

- Pesa unos 2 GB (PyTorch + modelo): convendría descargarlo solo si se activa la función.
- En CPU tarda varios minutos por canción (en la i9 unos 3–5 min).

## 6. Mejoras del editor de recorte

- **Zoom en la onda:** en mezclas de una hora cada píxel equivale a varios segundos;
  hoy la precisión se logra escribiendo los tiempos. Un zoom (pellizco o rueda)
  permitiría cortar a ojo con precisión de milisegundos.
- **Fundidos (fade in / fade out)** opcionales al guardar el recorte.
- **Ajustar al beat:** que los bordes "se peguen" a los golpes detectados en la onda.

## Descartado por ahora

- **Detección de BPM y tonalidad:** rekordbox y Serato ya lo hacen al analizar, y mejor.
