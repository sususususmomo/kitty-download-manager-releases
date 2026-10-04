"""Download one cover/thumbnail with yt-dlp, without processing media streams."""
from pathlib import Path
from urllib.parse import urlsplit


IMAGE_SUFFIXES = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "avif"}


def image_thumbnails(info):
    candidates = []
    for item in info.get("thumbnails") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
        except ValueError:
            continue
        candidates.append(dict(item))
    if not candidates and isinstance(info.get("thumbnail"), str):
        candidates = image_thumbnails({"thumbnails": [{"url": info["thumbnail"]}]})
    return candidates


def image_extension(path):
    with Path(path).open("rb") as source:
        header = source.read(32)
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    if header[:2] == b"BM":
        return ".bmp"
    if header[:4] in {b"II*\x00", b"MM\x00*"}:
        return ".tiff"
    if header[4:8] == b"ftyp" and (b"avif" in header[8:] or b"avis" in header[8:]):
        return ".avif"
    raise RuntimeError("Image téléchargée invalide : le serveur n’a pas fourni une image.")


def download_image(ydl, info, output_dir, stem, probe, check_control):
    """Use yt-dlp's thumbnail writer for selection, headers, cookies and fallback.

    This isolated adapter deliberately does not call process_ie_result: a
    collection's own cover must not trigger downloads of its entries. The
    private writer is covered by integration tests against the real yt-dlp.
    """
    from yt_dlp.utils import determine_ext

    check_control()
    image_info = dict(info)
    thumbnails = image_thumbnails(info)
    if not thumbnails:
        raise RuntimeError("Aucune miniature ou pochette disponible pour ce contenu.")
    for item in thumbnails:
        extension = str(item.get("ext") or determine_ext(item["url"], "jpg")).lower()
        item["ext"] = extension if extension in IMAGE_SUFFIXES else "jpg"
    image_info["thumbnails"] = thumbnails
    # This extension belongs only to the filename base passed to the writer.
    image_info["ext"] = "thumbnail"
    for index, item in enumerate(thumbnails):
        item["id"] = str(item.get("id") or index)
    ydl._sort_thumbnails(thumbnails)
    base = str(Path(output_dir) / (stem + ".thumbnail"))
    files = ydl._write_thumbnails("image", image_info, base)
    if not files:
        raise RuntimeError("Aucune image n’a pu être téléchargée.")
    image = Path(files[0][0])
    try:
        check_control()
        extension = image_extension(image)
        if probe is not None:
            has_audio, has_video = probe(image)
            if has_audio is True or has_video is False:
                raise RuntimeError("Image téléchargée invalide : fichier image illisible.")
        target = image.with_suffix(extension)
        if target != image:
            if target.exists():
                raise RuntimeError("Le fichier image de destination existe déjà.")
            image.rename(target)
        return target
    except Exception:
        image.unlink(missing_ok=True)
        raise
