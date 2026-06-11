const { chromium } = require('playwright');

const baseUrl = process.env.MC_SMOKE_BASE_URL || 'http://127.0.0.1:5173';
function urlFor(path) {
  if (!baseUrl.startsWith('file://')) return `${baseUrl}${path}`;
  if (path === '/') return baseUrl;
  return `${baseUrl}${path.replace(/^\/#/, '#')}`;
}
const routes = [
  ['home-terminal', '/', '明仓终端'],
  ['pulse', '/#/pulse', '今日持仓裁决'],
  ['reports', '/#/reports', '复盘案卷'],
  ['memory-legacy', '/#/memory', '复盘案卷'],
  ['reviews-legacy', '/#/reviews', '复盘案卷'],
  ['chat', '/#/chat', '研究副驾驶'],
  ['positions', '/#/positions', '持仓纪律'],
  ['health', '/#/health', '来源健康'],
  ['admin', '/#/admin', '规则与信任治理台'],
  ['stock', '/#/stock/300308', '个股案卷'],
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const consoleErrors = [];
  const pageErrors = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.addInitScript(() => localStorage.setItem('mc_proto_wizard_done_v1', '1'));
  const results = [];

  for (const [name, path, text] of routes) {
    await page.goto(urlFor(path), { waitUntil: 'networkidle' });
    await page.waitForSelector(`text=${text}`, { timeout: 10000 });
    results.push({ name, path, ok: true, title: await page.title() });
  }

  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  const emptyDeskCount = await page.locator('text=结果驾驶台').count();
  if (emptyDeskCount !== 0) throw new Error('结果驾驶台 should be hidden before the first conversation');
  await page.locator('.command-input input').fill('复盘上周卖飞的仓位');
  await page.locator('.command-input button[type="submit"]').click();
  await page.waitForSelector('text=复盘候选已生成', { timeout: 10000 });
  await page.waitForSelector('text=确认写入复盘案卷', { timeout: 10000 });
  await page.waitForSelector('text=结果驾驶台', { timeout: 10000 });
  await page.locator('.desk-pending').getByRole('button', { name: '确认' }).click();
  await page.locator('.desk-pending').getByText('已确认').waitFor({ timeout: 10000 });
  await page.waitForTimeout(900);
  await page.screenshot({ path: '/private/tmp/mingcang_frontend_v2/shots/v2-home-terminal.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileResults = [];
  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.waitForSelector('text=明仓终端', { timeout: 10000 });
  await page.waitForTimeout(900);
  await page.screenshot({ path: '/private/tmp/mingcang_frontend_v2/shots/v2-mobile-home-terminal.png', fullPage: true });
  for (const [name, path, text] of [
    ['reports-mobile', '/#/reports', '复盘案卷'],
  ]) {
    await page.goto(urlFor(path), { waitUntil: 'networkidle' });
    await page.waitForSelector(`text=${text}`, { timeout: 10000 });
    mobileResults.push({ name, path, ok: true });
  }
  await page.waitForTimeout(900);
  await page.screenshot({ path: '/private/tmp/mingcang_frontend_v2/shots/v2-mobile-memory.png', fullPage: true });

  await browser.close();

  const payload = { results, mobileResults, consoleErrors, pageErrors };
  console.log(JSON.stringify(payload, null, 2));
  if (consoleErrors.length || pageErrors.length) process.exit(1);
})();
