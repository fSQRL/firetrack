// Captures pour l'analyse air : couche qualité de l'air activée, nuit toxique vs après-midi
import puppeteer from 'puppeteer-core';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const shots = [
  { t: Date.UTC(2026, 6, 27, 1, 0) / 1000, out: 'air_app_nuit27.png' },   // 3h locale : le pic nocturne
  { t: Date.UTC(2026, 6, 24, 12, 0) / 1000, out: 'air_app_aprem24.png' }, // 14h locale : flammes fortes, air correct
];
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1000, height: 780 });
for (const s of shots) {
  await page.goto(`http://localhost:5173/?t=${s.t}`, { waitUntil: 'networkidle2', timeout: 30000 });
  await page.waitForSelector('.loader-close', { timeout: 30000 });
  await page.click('.loader-close');
  // cocher la couche qualité de l'air (2e checkbox de la barre)
  await page.evaluate(() => document.querySelectorAll('.btn.sat input')[1].click());
  await new Promise((r) => setTimeout(r, 2500));
  await page.screenshot({ path: new URL(`../public/analyse/air/${s.out}`, import.meta.url).pathname.slice(1) });
  console.log(s.out, 'ok');
}
await browser.close();
