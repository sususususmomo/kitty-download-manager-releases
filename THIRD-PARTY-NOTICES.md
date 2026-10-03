# Composants téléchargés par l’installateur Windows

Le ZIP Kitty contient les sources du projet et ses scripts d’installation.
L’installateur récupère séparément les composants suivants sur leurs sources
officielles; les URL, versions et sommes de contrôle sont conservées dans
`python-dependencies.json` et `binary-dependencies.json` de la version installée.

- CPython 3.13.16 : https://www.python.org/ — licence Python/PSF, texte inclus
  dans le runtime embarqué téléchargé.
- pip : https://pypi.org/project/pip/ — licence MIT, notices du wheel téléchargé.
- yt-dlp et ses dépendances : https://github.com/yt-dlp/yt-dlp
- Mutagen : https://github.com/quodlibet/mutagen
- psutil : https://github.com/giampaolo/psutil
- FFmpeg/ffprobe, build Windows GPL sélectionné :
  https://github.com/yt-dlp/FFmpeg-Builds et https://ffmpeg.org/legal.html
- Deno : https://github.com/denoland/deno

Les notices et licences des wheels Python restent dans les répertoires
`.dist-info` des packages installés. Les exécutables FFmpeg et Deno sont copiés
depuis leurs archives de release; les textes de licence présents dans ces
archives sont conservés dans `notices` lorsqu’ils sont disponibles.
