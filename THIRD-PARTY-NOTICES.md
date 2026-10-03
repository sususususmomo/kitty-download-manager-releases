# Composants téléchargés par les installateurs

Le ZIP Kitty contient les sources du projet et ses scripts d’installation.
Les installateurs récupèrent séparément les composants suivants; les URL,
versions et sommes de contrôle sont conservées dans
`python-dependencies.json` et `binary-dependencies.json` de la version installée.

- CPython 3.13.16 : https://www.python.org/ — licence Python/PSF, texte inclus
  dans le runtime embarqué téléchargé.
- CPython privé macOS : build `install_only_stripped` 20261001 du projet Astral
  https://github.com/astral-sh/python-build-standalone — Python 3.13.16 et notices
  présentes dans l’archive. Ce build est fourni par Astral.
- pip : https://pypi.org/project/pip/ — licence MIT, notices du wheel téléchargé.
- yt-dlp et ses dépendances : https://github.com/yt-dlp/yt-dlp
- Mutagen : https://github.com/quodlibet/mutagen
- psutil : https://github.com/giampaolo/psutil
- FFmpeg/ffprobe, build Windows GPL sélectionné :
  https://github.com/yt-dlp/FFmpeg-Builds et https://ffmpeg.org/legal.html
- FFmpeg/ffprobe macOS 9.0.2 : builds signés de Martin Riedl
  https://ffmpeg.martin-riedl.de/ — builds GPL v3 avec codecs supplémentaires.
  Configuration et sources de compilation :
  https://git.martin-riedl.de/ffmpeg/build-script
  Les ZIP Kitty ne redistribuent pas ces exécutables ; ils sont téléchargés
  séparément par l’installateur. Les notices présentes dans les archives sont
  conservées dans `notices` de la version installée.
- Deno : https://github.com/denoland/deno
  macOS : version 2.9.7 fixée, archives Intel et Apple Silicon vérifiées par SHA-256.
  https://github.com/denoland/deno/releases/tag/v2.9.7

Les notices et licences des wheels Python restent dans les répertoires
`.dist-info` des packages installés. Les exécutables FFmpeg et Deno sont copiés
depuis leurs archives de release; les textes de licence présents dans ces
archives sont conservés dans `notices` lorsqu’ils sont disponibles.
