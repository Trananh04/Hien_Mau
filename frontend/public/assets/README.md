# Blood bank landing-page assets

Source: screenshot provided in the conversation (1672 × 941 px). These are *presentation assets*, not the website implementation.

## Asset directory

- `svg/logo-mark.svg` — clean, traced red mark, transparent; place at 45–52px high in header.
- `png/logo-mark-red.png`, `png/logo-mark-white.png` — cropped mark from source, alpha transparent; red for header, white for dark footer.
- `svg/heart-blood-drop-vector.svg` — scalable recreation of the red heart + drop graphic; ideal for hero right.
- `svg/dong-son-drum.svg` — transparent, pale pink Vietnamese drum ornament, newly traced as repeatable shapes (not a pixel-perfect copy).
- `svg/hero-base.svg` — light pink/white hero background, no text or menus.
- `svg/hero-waves.svg` — isolated ribbon waves for the *bottom* of hero (transparent).
- `svg/footer-background.svg` — red gradient footer and waves, no text.
- `svg/icon-blood-drop.svg` — a small blood drop outline.
- `png/*.png` — useful rendered previews for SVG assets.
- `news/01..07-*.png` — thumbnail crops from the screenshot; each is only about 200×88px, replace with licensed full-res original photos in production.

## Recommended layout

Header: HTML/CSS for title/navigation; logo-mark-red.png or svg for logo icon.
Hero: place hero-base.svg as background; drum at upper-right (opacity 0.7); heart at right, behind content; hero-waves.svg at bottom, full width; all headings and CTAs as real HTML.
News: use semantic cards and separate image assets. For a responsive layout, use CSS Grid with 3/2/1 columns depending on screen width, not 7 tiny cards forced into a narrow mobile view.
Footer: footer-background.svg cover/100% 100%; white logo above actual HTML links.

Sample CSS:

```css
.hero {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  min-height: 350px;
  background: url('/assets/svg/hero-base.svg') center / cover no-repeat;
}
.hero-drum {
  position: absolute; z-index: -1;
  width: min(600px, 52vw); right: -75px; top: -245px;
  opacity: .7;
}
.hero-heart {
  position: absolute; z-index: -1;
  right: 5%; bottom: 40px; width: clamp(110px, 14vw, 210px);
}
.hero-waves {
  position: absolute; z-index: -1;
  inset: auto 0 0; width: 100%; height: 165px;
  object-fit: fill; pointer-events: none;
}
.footer { background: url('/assets/svg/footer-background.svg') center / 100% 100% no-repeat; }
@media (max-width: 768px) {
  .hero-drum,.hero-heart { opacity: .14; }
  .hero-waves { height: 95px; }
}
```

The source image is AI-generated/mockup artwork. News/card copy and pictured events should not be treated as verified factual content. Check trademarks and image usage rights before publishing.
