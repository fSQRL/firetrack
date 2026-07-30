// Capture d'écran du site pour la page d'analyse
import puppeteer from 'puppeteer-core';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1100, height: 800 });
await page.goto('http://localhost:5173', { waitUntil: 'networkidle2', timeout: 30000 });
await page.waitForSelector('.loader-close', { timeout: 30000 });
await page.click('.loader-close');
await new Promise((r) => setTimeout(r, 4000)); // laisse la lecture animer traces et flammes
await page.screenshot({ path: new URL('../public/analyse/apercu_site.png', import.meta.url).pathname.slice(1) });
await browser.close();
console.log('capture ok');
