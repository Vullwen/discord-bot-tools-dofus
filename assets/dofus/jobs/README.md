# DOFUS job icons

Source: DofusDB public API.

- Metadata endpoint: `https://api.dofusdb.fr/jobs?$limit=100`
- Icon URLs: `https://api.dofusdb.fr/img/jobs/<iconId>.png`
- `manifest.json` maps each French job name to its local PNG file.
- Local files use French ASCII slugs, for example `bucheron.png` and `pecheur.png`.

The API currently exposes `.jpg` URLs in the `img` field, but the available icon
files are PNGs.
