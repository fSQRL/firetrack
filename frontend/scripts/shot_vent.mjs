// Captures pour l'analyse vent : le panache avant/après la rotation du vent
import puppeteer from 'puppeteer-core';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const shots = [
  { t: Date.UTC(2026, 6, 23, 15, 0) / 1000, out: 'vent_app_23juil.png' }, // vent de NE : panache vers l'océan
  { t: Date.UTC(2026, 6, 25, 15, 0) / 1000, out: 'vent_app_25juil.png' }, // vent d'O : panache vers les terres
];
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1000, height: 780 });
for (const s of shots) {
  await page.goto(`http://localhost:5173/?t=${s.t}`, { waitUntil: 'networkidle2', timeout: 30000 });
  await page.waitForSelector('.loader-close', { timeout: 30000 });
  await page.click('.loader-close');
  await new Promise((r) => setTimeout(r, 2500));
  await page.screenshot({ path: new URL(`../public/analyse/vent/${s.out}`, import.meta.url).pathname.slice(1) });
  console.log(s.out, 'ok');
}
await browser.close();
