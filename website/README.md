# Sacred Plains Ranch — White Buffalo Website

A static marketing site for a ranch that **specializes in white buffalo**. The
business sells two things:

1. **Breeding rights** to its proven white bulls and cows.
2. **Offspring** — the white calves (and bred heifers / genetics) produced by the herd.

## Files
- `index.html` — single-page site (hero, breeding rights & offspring, about, trust, calves, contact, footer).
- `styles.css` — all styling. Fonts: Oswald + Inter (Google Fonts).
- `assets/white-buffalo-hero.svg` — the hero illustration: a **white buffalo** on the prairie at dawn. Self-contained inline SVG, no external image dependencies.

## Run locally
Open `index.html` in a browser, or serve the folder:

```bash
cd website
python3 -m http.server 8000
# visit http://localhost:8000
```

## Notes
- The hero image is the white buffalo, per the ranch's specialty.
- The contact and newsletter forms are front-end only; wire them to a backend
  or a form service (e.g. Netlify Forms) before going live.
