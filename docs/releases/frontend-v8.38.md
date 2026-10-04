## English

**Image only** is now available below Playlist in the format menu. It downloads the thumbnail or cover in its original image format, without downloading audio/video. Format and playlist controls are disabled while it is active; previous selections are restored when it is turned off. The mode also applies to Kitty’s floating button and context menu.

Requires **Kitty Backend v8.32 or later**. A collection’s own cover is supported when the site supplies one. Results use the normal queue and history, with clear errors for missing or invalid images. The extension targets desktop Firefox 140+ and the XPI remains unsigned until Mozilla signs it.

## Français

**Image uniquement** apparaît sous Playlist dans le menu des formats. Ce mode récupère la miniature ou la pochette dans son format image d’origine, sans télécharger l’audio/vidéo. Les réglages de format et de playlist sont grisés ; leur sélection précédente est restaurée quand le mode est désactivé. Le pill et le menu contextuel utilisent aussi ce choix.

Nécessite **Kitty Backend v8.32 ou plus récent**. La pochette d’une collection est prise en charge si le site en fournit une. Les images utilisent la file et l’historique habituels, avec des erreurs explicites si l’image manque ou est invalide. Firefox desktop 140+ ; XPI non signé, à soumettre à Mozilla.

Commande complète fish, dans le même dossier :

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.38.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Reload the temporary Firefox extension after installation. / Recharger l’extension temporaire Firefox après installation.

Validation details: [frontend v8.38](https://github.com/sususususmomo/kitty-download-manager-releases/blob/main/docs/validation-frontend-v8.38.json).
