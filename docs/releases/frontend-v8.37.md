Firefox frontend v8.37, compatible with backend v8.31 / native protocol 1.

- UI elements are created directly through the DOM: titles, errors, diagnostics and URLs are never parsed as HTML.
- Source SVG icons keep the same geometry and use the SVG namespace.
- Queue and history rendering, source buttons, animated cats and pill previews preserve the existing CSS and interactions.
- Mozilla validator: no errors or unsafe HTML warnings; the remaining warning concerns Firefox Android, which Kitty does not support.

The unsigned XPI is intended for Mozilla submission. The complete ZIP includes the sources and installers in one `kitty-download-manager` folder. Signature and publication on Mozilla Add-ons remain pending.

## Français

Interface Firefox v8.37, compatible avec le backend v8.31 / protocole natif 1.

- Les titres, erreurs, diagnostics et URLs sont insérés comme du texte, sans analyse HTML.
- Les icônes SVG conservent leurs tracés et utilisent leur namespace.
- La file, l’historique, les boutons source, les chats animés et les aperçus du pill conservent les styles et interactions.
- Validateur Mozilla : aucune erreur ni alerte HTML ; l’avertissement restant concerne Android, non pris en charge par Kitty.

Le XPI non signé est destiné à la soumission Mozilla. Le ZIP complet contient les sources et les installateurs dans un seul dossier `kitty-download-manager`. La signature et la publication Mozilla restent à effectuer.

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.37.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Recharger l’extension temporaire dans `about:debugging`.
