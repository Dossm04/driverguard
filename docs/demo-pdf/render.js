// HTML → PDF через Chromium Playwright: node render.js in.html out.pdf
const path = require('path');
// Playwright берём из web/node_modules независимо от расположения скрипта
const pw = require(require.resolve('@playwright/test', { paths: [process.cwd(), path.join(__dirname, '..', '..', 'web')] }));
const { chromium } = pw;
const fs = require('fs');
const [,, input, output] = process.argv;
(async () => {
  const exe = fs.existsSync('/opt/pw-browsers/chromium') ? { executablePath: '/opt/pw-browsers/chromium' } : {};
  const browser = await chromium.launch(exe);
  const page = await browser.newPage();
  await page.goto('file://' + path.resolve(input), { waitUntil: 'load' });
  await page.emulateMedia({ media: 'print' });
  await page.pdf({
    path: output, format: 'A4', printBackground: true, preferCSSPageSize: true,
    margin: { top: '16mm', bottom: '16mm', left: '14mm', right: '14mm' },
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: '<div style="width:100%;font-size:8px;color:#64748B;padding:0 14mm;display:flex;justify-content:space-between;font-family:DejaVu Sans,Liberation Sans,sans-serif"><span>DriverGuard · Fleet Safety</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
  });
  await browser.close();
  console.log('pdf', output);
})().catch((e) => { console.error(e); process.exit(1); });
