# Blood bank landing-page assets

Source: screenshot provided in the conversation (1672 × 941 px). These are *presentation assets*, not the website implementation.

## Asset directory

- `svg/logo-mark.svg` — clean, traced red mark, transparent; place at 45–52px high in header.
- `png/logo-mark-red.png`, `png/logo-mark-white.png` — cropped mark from source, alpha transparent; red for header, white for dark footer.
- `svg/heart-blood-drop-vector.svg` — scalable recreation of the red heart + drop graphic; ideal for hero right.
- `svg/dong-son-drum.svg` (đỏ, nền sáng) và `svg/dong-son-drum-light.svg` (trắng, nền đỏ) — mặt trống đồng Đông Sơn (hoa văn kiểu trống Ngọc Lũ: sao 14 cánh, chim Lạc, nhà sàn, hươu). Nguồn: Wikimedia Commons, "Trống đồng Đông Sơn.svg" của Tom Mai, **Public Domain** — https://commons.wikimedia.org/wiki/File:Tr%E1%BB%91ng_%C4%91%E1%BB%93ng_%C4%90%C3%B4ng_S%C6%A1n.svg. Đã đổi màu, bỏ đĩa nền trắng và nén bằng SVGO (2,4 MB → 429 KB).
- `svg/hero-base.svg` — light pink/white hero background, no text or menus.
- `svg/hero-waves.svg` — isolated ribbon waves for the *bottom* of hero (transparent).
- (Chân trang: nền gradient bằng CSS + sóng SVG nhúng trong `partials/footer.html`, chiều cao cố định để không che chữ.)
- `svg/icon-blood-drop.svg` — a small blood drop outline.
- `png/*.png` — useful rendered previews for SVG assets.

## Recommended layout

Header: HTML/CSS for title/navigation; logo-mark-red.png or svg for logo icon.
Hero: place hero-base.svg as background; drum at upper-right (opacity 0.7); heart at right, behind content; hero-waves.svg at bottom, full width; all headings and CTAs as real HTML.
Footer: sóng SVG nhúng (không kéo giãn ảnh nền), logo trắng phía trên các liên kết HTML thật.

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
@media (max-width: 768px) {
  .hero-drum,.hero-heart { opacity: .14; }
  .hero-waves { height: 95px; }
}
```

The source image is AI-generated/mockup artwork. News/card copy and pictured events should not be treated as verified factual content. Check trademarks and image usage rights before publishing.
