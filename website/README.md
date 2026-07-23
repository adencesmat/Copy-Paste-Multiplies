# Biz Family Autos — Hand Car Wash & Detailing Website

A conversion-focused marketing site for **Biz Family Autos**, a family-run
**100% hand car wash and auto detailing** business serving Garden City,
Medford, and Long Island, NY since 1979.

The site is built to **generate revenue**: it leads with clear wash pricing,
detailing packages, a recurring **Unlimited Wash membership**, upsell add-ons,
fleet/gift-card offers, strong calls-to-action, and a booking/quote lead form.

## Business details
- **Phone:** (516) 220-3000
- **Garden City:** 3 Commercial Avenue, Garden City, NY 11530
- **Medford:** Medford, NY (Suffolk County)
- Update prices, hours, and the Medford street address with the owner's exact
  figures before going fully live — the numbers shown are realistic starting
  estimates.

## Files
- `index.html` — single-page site: hero, wash menu, detailing packages,
  unlimited membership, add-ons, why-us, how-it-works, reviews, fleet/gift
  promos, locations, booking form, FAQ, final CTA, footer.
- `styles.css` — all styling. Fonts: Oswald + Inter (Google Fonts).
- `assets/hero-car-wash.svg` — self-contained hero illustration (a
  hand-washed, glossy car with water beading). No external image dependencies.

## Revenue / conversion features
- Sticky header **Book Now** CTA + click-to-call phone number.
- Sticky mobile call/book bar.
- Tiered wash pricing with a highlighted "Most Popular" package.
- Detailing tiers with a premium ceramic-coating upsell.
- **Unlimited Wash membership** for recurring monthly revenue.
- À-la-carte add-ons, fleet accounts, and gift cards.
- Lead-capture booking form + newsletter signup (Netlify Forms).
- `LocalBusiness`/`AutoWash` JSON-LD structured data for local SEO.

## Forms (Netlify)
Two forms are wired for **Netlify Forms** (`data-netlify="true"` with a
honeypot): `booking` and `newsletter`. Submissions post via AJAX so the page
doesn't navigate away, and appear in the Netlify dashboard under *Forms*.
Set up notifications there to route leads to email/Slack.

## Deploy
`netlify.toml` at the repo root publishes this `website/` directory. Push to
the connected branch and Netlify builds automatically.

## Run locally
```bash
cd website
python3 -m http.server 8000
# visit http://localhost:8000
```
