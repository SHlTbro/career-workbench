import { pathToFileURL } from 'node:url';

const [htmlPath, pdfPath] = process.argv.slice(2);
if (!htmlPath || !pdfPath) throw new Error('HTML and PDF paths required');
const modulePath = process.env.CAREER_PLAYWRIGHT_MODULE || '';
if (!modulePath) throw new Error('Set CAREER_PLAYWRIGHT_MODULE to your playwright module (playwright/index.mjs)');
const browserPath = process.env.CAREER_CHROMIUM_PATH || '';
if (!browserPath) throw new Error('Set CAREER_CHROMIUM_PATH to your Chromium executable');
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({ executablePath: browserPath, headless: true });
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  const dom = await page.evaluate(() => ({
    projectIds: [...document.querySelectorAll('[data-project-id]')].map((item) => item.dataset.projectId),
    heroCount: document.querySelectorAll('[data-tier="HERO"]').length,
    compactLineCounts: [...document.querySelectorAll('p.compact')].map((item) => {
      const style = getComputedStyle(item);
      return { projectId: item.parentElement.dataset.projectId,
        lines: Math.ceil(item.getBoundingClientRect().height / parseFloat(style.lineHeight) - 0.02) };
    }),
  }));
  await page.pdf({ path: pdfPath, format: 'A4', preferCSSPageSize: true,
    printBackground: true, displayHeaderFooter: false });
  process.stdout.write(JSON.stringify(dom));
} finally {
  await browser.close();
}
