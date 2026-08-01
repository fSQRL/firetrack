// Capture de présentation pour le README
import puppeteer from 'puppeteer-core';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 800 });
await page.goto(`http://localhost:5173/?t=${Date.UTC(2026, 6, 24, 15, 30) / 1000}`, { waitUntil: 'networkidle2', timeout: 30000 });
await page.waitForSelector('.loader-close', { timeout: 30000 });
await page.click('.loader-close');
await new Promise((r) => setTimeout(r, 3000));
await page.screenshot({ path: new URL('../../docs/screenshot_carte.png', import.meta.url).pathname.slice(1) });
console.log('ok');
await browser.close();
