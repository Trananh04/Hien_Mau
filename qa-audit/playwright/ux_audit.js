/**
 * UX/UI audit tự động trên môi trường QA (Playwright + @axe-core/playwright).
 * Tiêu chí: vercel-labs/web-interface-guidelines, ui-ux-pro-max (44px, 8px, 4.5:1, 375/768/1024/1440),
 * WCAG 2.2 AA (axe: wcag2a, wcag2aa, wcag21aa, wcag22aa — gồm target-size 24px).
 *
 * Mỗi trang × vai trò × khung nhìn đo:
 *  - axe violations                       (lỗi xác nhận theo chuẩn)
 *  - vùng bấm < 24px (WCAG 2.5.8 — lỗi) / < 44px trên mobile (ui-ux-pro-max — đề xuất)
 *  - focus khi Tab: phần tử không có chỉ báo focus nhìn thấy được (lỗi) / bị header dính che (lỗi)
 *  - hover: nút không đổi gì khi rê chuột (đề xuất)
 *  - phân cấp nút: >1 nút primary trong cùng một khối (đề xuất)
 *  - tràn ngang ở 320/375/768/1024/1440 (lỗi)
 *  - heading: số <h1>, skip link
 * Chạy: node ux_audit.js  (env QA_BASE_URL, QA_ACCOUNT_PASSWORD, QA_UX_OUT)
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { AxeBuilder } = require('@axe-core/playwright');

const BASE = (process.env.QA_BASE_URL || 'http://host.docker.internal:8091').replace(/\/$/, '');
const PW = process.env.QA_ACCOUNT_PASSWORD;
const OUT = process.env.QA_UX_OUT || `evidence/runs/ux-${Date.now()}`;
fs.mkdirSync(OUT, { recursive: true });

const ROLES = {
  anon: { login: null, pages: ['/', '/dot-hien/', '/dot-hien/2/', '/ban-do/', '/dang-nhap/', '/dang-ky/', '/quen-mat-khau/', '/benh-vien/dang-nhap/'] },
  member: { login: ['/dang-nhap/', 'an.nguyen@demo.vn'], pages: ['/tai-khoan/', '/tai-khoan/don-dang-ky/', '/tai-khoan/lich-su-hien/', '/tai-khoan/yeu-cau-can-mau/', '/can-mau/gui-yeu-cau/', '/thong-bao/'] },
  hospital: { login: ['/benh-vien/dang-nhap/', 'benhvien1@hienmau.vn'], pages: ['/benh-vien/', '/benh-vien/dot-hien/', '/benh-vien/dot-hien/2/', '/benh-vien/dot-hien/2/diem-hien/', '/benh-vien/cho-xet-nghiem/', '/benh-vien/kho/', '/benh-vien/kho/phieu/xuat/', '/benh-vien/nhu-cau/', '/benh-vien/tim-nguon/?blood_group=O%2B&product=2', '/benh-vien/yeu-cau-can-mau/', '/benh-vien/de-nghi-den/'] },
  admin: { login: ['/quan-tri/dang-nhap/', 'admin@hienmau.vn'], pages: ['/quan-tri/thong-ke/', '/quan-tri/nguoi-dung/', '/quan-tri/benh-vien/', '/quan-tri/cau-hinh/', '/danh-muc/'] },
};
const VIEWPORTS = Object.fromEntries(Object.entries({ desktop: [1440, 900], mobile: [375, 812] })
  .filter(([k]) => !process.env.QA_UX_VIEWPORTS || process.env.QA_UX_VIEWPORTS.split(',').includes(k)));
const WIDTHS = [320, 375, 768, 1024, 1440];

async function go(page, url) {
  for (let i = 0; i < 3; i++) {
    try { return await page.goto(url, { waitUntil: 'load', timeout: 45000 }); } catch (e) { if (i === 2) throw e; await page.waitForTimeout(2000); }
  }
}

async function login(page, [portal, email]) {
  await go(page, BASE + portal);
  await page.fill('input[name=email]', email);
  await page.fill('input[name=password]', PW);
  await Promise.all([page.waitForNavigation({ waitUntil: 'load', timeout: 45000 }), page.click('form button[type=submit]')]);
}

/* Đo trong trang: vùng bấm, phân cấp nút, heading, skip link */
const measure = () => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && (!window.__onscreenOnly || (r.bottom > 0 && r.right > 0)) && s.visibility !== 'hidden' && s.display !== 'none' && !el.closest('[hidden],dialog:not([open])'); };
  const desc = (el) => { const t = (el.getAttribute('aria-label') || el.innerText || el.value || el.title || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}${t ? ` “${t}”` : ''}`; };
  const inlineText = (el) => el.tagName === 'A' && el.closest('p, li, td, dd, .field-help, .cell-sub, .small') && !el.classList.contains('btn');
  const targets = [...document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button], summary, label.check-row, label:has(input[type=radio])')]
    .filter(vis).filter(el => !(el.tagName === 'INPUT' && ['radio', 'checkbox'].includes(el.type) && el.closest('label')));
  const small24 = [], small44 = [];
  for (const el of targets) {
    if (inlineText(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) small24.push(`${desc(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
    else if (r.width < 44 || r.height < 44) small44.push(`${desc(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
  }
  const groups = [...document.querySelectorAll('form, .panel, .modal-dialog[open], .table-actions, .ws-actions, .card, section')];
  const multiPrimary = [];
  for (const g of groups) {
    const prim = [...g.querySelectorAll(':scope .btn.primary')].filter(vis).filter(b => b.closest('form, .panel, .modal-dialog, .table-actions, .ws-actions, .card, section') === g);
    if (prim.length > 1) multiPrimary.push(`${desc(g)}: ${prim.map(desc).join(' | ')}`);
  }
  const rowsWithPrimary = [...document.querySelectorAll('tbody tr')].filter(tr => tr.querySelector('.btn.primary')).length;
  return {
    targets: targets.length, small24, small44, multiPrimary, rowsWithPrimary,
    h1: [...document.querySelectorAll('h1')].filter(vis).length,
    skipLink: !!document.querySelector('a[href="#main"], a.skip-link'),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
};

/* Tab qua tối đa 30 phần tử: có chỉ báo focus nhìn thấy không, có bị header dính che không */
async function focusAudit(page) {
  const noRing = [], covered = [];
  await page.evaluate(() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); });
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const s = getComputedStyle(el);
      const ring = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || (s.boxShadow && s.boxShadow !== 'none');
      const r = el.getBoundingClientRect();
      let hidden = false;
      const top = document.elementFromPoint(Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1), Math.min(Math.max(r.top + Math.min(r.height / 2, 8), 1), innerHeight - 1));
      if (top && !el.contains(top) && !top.contains(el) && getComputedStyle(top.closest('header, .topbar, .ws-topbar, nav') || document.body).position.match(/sticky|fixed/)) hidden = true;
      const t = (el.getAttribute('aria-label') || el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 30);
      return { ring, hidden, d: `${el.tagName.toLowerCase()}${t ? ` “${t}”` : ''}`, visible: r.width > 0 && r.height > 0 };
    });
    if (!info) break;
    if (info.visible && !info.ring) noRing.push(info.d);
    if (info.hidden) covered.push(info.d);
  }
  return { noRing: [...new Set(noRing)], covered: [...new Set(covered)] };
}

/* Hover: nút có thay đổi gì khi rê chuột không */
async function hoverAudit(page) {
  const btns = page.locator('.btn:visible, button:visible');
  const n = Math.min(await btns.count(), 8), none = [];
  for (let i = 0; i < n; i++) {
    const b = btns.nth(i);
    if (await b.isDisabled().catch(() => true)) continue;
    const snap = () => b.evaluate(el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color, s.boxShadow, s.transform, s.borderColor, s.textDecorationLine, s.filter].join('|'); });
    const before = await snap().catch(() => null);
    await b.hover({ timeout: 1500 }).catch(() => {});
    await page.waitForTimeout(260);
    const after = await snap().catch(() => null);
    if (before && after && before === after) none.push(await b.evaluate(el => (el.innerText || el.getAttribute('aria-label') || el.className).trim().slice(0, 30)));
    await page.mouse.move(0, 0);
  }
  return none;
}

(async () => {
  const browser = await chromium.launch();
  const report = [];
  for (const [vpName, [w, h]] of Object.entries(VIEWPORTS)) {
    for (const [role, cfg] of Object.entries(ROLES)) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, locale: 'vi-VN', hasTouch: vpName === 'mobile', isMobile: vpName === 'mobile' });
      const page = await ctx.newPage();
      if (cfg.login) await login(page, cfg.login);
      for (const p of cfg.pages) {
       try {
        await go(page, BASE + p);
        await page.waitForTimeout(400);
        const name = `${vpName}_${role}_${p.replace(/[/?=&%]+/g, '_').replace(/^_|_$/g, '') || 'home'}`;
        await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
        if (process.env.QA_UX_ONSCREEN === '1') await page.evaluate(() => { window.__onscreenOnly = true; });
        const m = await page.evaluate(measure);
        const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).exclude('.leaflet-container').analyze();
        const entry = { viewport: vpName, role, path: p, screenshot: `${name}.png`, ...m,
          axe: axe.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length, target: v.nodes[0] && v.nodes[0].target.join(' '), html: v.nodes[0] && v.nodes[0].html.slice(0, 160) })) };
        if (vpName === 'desktop') { Object.assign(entry, await focusAudit(page)); entry.noHover = await hoverAudit(page); }
        if (vpName === 'desktop' && ['/', '/benh-vien/', '/benh-vien/kho/', '/tai-khoan/', '/quan-tri/nguoi-dung/', '/benh-vien/dot-hien/2/diem-hien/'].includes(p)) {
          entry.widths = {};
          for (const ww of WIDTHS) { await page.setViewportSize({ width: ww, height: 900 }); await page.waitForTimeout(150);
            entry.widths[ww] = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth); }
          await page.setViewportSize({ width: w, height: h });
        }
        report.push(entry);
        fs.writeFileSync(path.join(OUT, 'ux_report.json'), JSON.stringify(report, null, 1));
        console.log(`${vpName.padEnd(7)} ${role.padEnd(8)} ${p.padEnd(42)} axe:${entry.axe.length} <24:${m.small24.length} <44:${m.small44.length} prim:${m.multiPrimary.length}`
          + (entry.noRing ? ` noFocus:${entry.noRing.length} covered:${entry.covered.length} noHover:${entry.noHover.length}` : '') + (m.overflow > 1 ? ` OVERFLOW:${m.overflow}` : ''));
       } catch (e) { console.log(`LỖI ĐO ${vpName} ${role} ${p}: ${e.message.split(String.fromCharCode(10))[0]}`); }
      }
      await ctx.close();
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, 'ux_report.json'), JSON.stringify(report, null, 1));
})();
