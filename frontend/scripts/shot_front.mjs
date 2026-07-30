// Captures de l'app pour l'analyse "front" : instants précis via ?t=
import puppeteer from 'puppeteer-core';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const shots = [
  // le front est martelé, 24/07 fin d'après-midi (19h locale)
  { t: Date.UTC(2026, 6, 24, 17, 0) / 1000, out: 'front_app_24juil.png' },
  // le lendemain à la même heure : le front tient
  { t: Date.UTC(2026, 6, 25, 17, 0) / 1000, out: 'front_app_25juil.png' },
];
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1000, height: 780 });
for (const s of shots) {
  await page.goto(`http://localhost:5173/?t=${s.t}`, { waitUntil: 'networkidle2', timeout: 30000 });
  await page.waitForSelector('.loader-close', { timeout: 30000 });
  await page.click('.loader-close');
  await new Promise((r) => setTimeout(r, 2500));
  await page.screenshot({ path: new URL(`../public/analyse/front/${s.out}`, import.meta.url).pathname.slice(1) });
  console.log(s.out, 'ok');
}
await browser.close();
