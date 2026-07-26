// Diagnostic headless : charge l'app, capture console + screenshot
import puppeteer from 'puppeteer-core';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true, args: ['--window-size=900,900'] });
const page = await browser.newPage();
await page.setViewport({ width: 900, height: 900 });
page.on('console', (m) => console.log('[console]', m.type(), m.text()));
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto('http://localhost:5173', { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 5000));
const state = await page.evaluate(() => {
  const c = document.querySelector('.trail-canvas');
  const cs = c ? getComputedStyle(c) : null;
  return {
    canvases: document.querySelectorAll('.trail-canvas').length,
    canvas: c ? {
      attrW: c.width, attrH: c.height,
      clientW: c.clientWidth, clientH: c.clientHeight,
      position: cs.position, cssW: cs.width, zIndex: cs.zIndex,
    } : null,
    markers: document.querySelectorAll('.plane-marker').length,
    clock: document.querySelector('.bigclock')?.textContent,
  };
});
console.log('[state]', JSON.stringify(state));
await page.screenshot({ path: new URL('./check.png', import.meta.url).pathname.slice(1) });
await browser.close();
