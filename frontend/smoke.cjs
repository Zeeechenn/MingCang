const { chromium } = require('playwright');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const baseUrl = process.env.MC_SMOKE_BASE_URL || 'http://127.0.0.1:4174';
const shotsDir = process.env.MC_SMOKE_SHOTS_DIR || path.join(os.tmpdir(), 'mingcang_frontend_v2', 'shots');
let staticServer = null;

async function ensureStaticServer() {
  if (process.env.MC_SMOKE_BASE_URL) return;
  const root = path.resolve(__dirname, 'dist');
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
  staticServer = http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, baseUrl).pathname);
    const candidate = pathname === '/' ? 'index.html' : pathname.replace(/^\//, '');
    const file = path.join(root, candidate);
    const target = file.startsWith(root) && fs.existsSync(file) && fs.statSync(file).isFile()
      ? file
      : path.join(root, 'index.html');
    res.writeHead(200, { 'Content-Type': types[path.extname(target)] || 'application/octet-stream' });
    fs.createReadStream(target).pipe(res);
  });
  await new Promise((resolve) => staticServer.listen(4174, '127.0.0.1', resolve));
}
function urlFor(path) {
  if (!baseUrl.startsWith('file://')) return `${baseUrl}${path}`;
  if (path === '/') return baseUrl;
  return `${baseUrl}${path.replace(/^\/#/, '#')}`;
}
const routes = [
  ['home-terminal', '/', '明仓终端'],
  ['daily', '/#/daily', '日常'],
  ['pulse', '/#/pulse', '今日持仓裁决'],
  ['stocks', '/#/stocks', '个股案卷'],
  ['reports', '/#/reports', '复盘案卷'],
  ['memory-legacy', '/#/memory', '复盘案卷'],
  ['reviews-legacy', '/#/reviews', '复盘案卷'],
  ['chat', '/#/chat', '研究副驾驶'],
  ['positions', '/#/positions', '持仓纪律'],
  ['memory-evolution', '/#/memory-evolution', '记忆进化'],
  ['health', '/#/health', '来源健康'],
  ['news-shadow', '/#/news-shadow', '新闻金字塔试用台'],
  ['admin', '/#/admin', '规则与信任治理台'],
  ['stock-cn', '/#/stock/CN/300308', '正式信号'],
  ['stock-hk', '/#/stock/HK/00700', '仅观察 · 非灰度白名单'],
  ['stock-us', '/#/stock/US/AAPL', '仅观察 · 非灰度白名单'],
];

(async () => {
  await ensureStaticServer();
  fs.mkdirSync(shotsDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const consoleErrors = [];
  const pageErrors = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(err.message));

  // 首次打开必须呈现可操作的三步向导，并让目标选择真正落到推荐页面。
  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    localStorage.removeItem('mc_proto_wizard_done_v1');
    localStorage.removeItem('mc_onboarding_goal_v1');
  });
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByRole('dialog', { name: '欢迎使用明仓' }).waitFor({ timeout: 10000 });
  await page.getByRole('button', { name: /研究一只股票/ }).click();
  await page.getByRole('button', { name: '继续' }).click();
  await page.getByRole('button', { name: '继续' }).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '完成并进入' }).click();
  await page.waitForURL(/#\/stocks$/);
  const selectedGoal = await page.evaluate(() => localStorage.getItem('mc_onboarding_goal_v1'));
  if (selectedGoal !== 'research') throw new Error(`onboarding goal was not persisted: ${selectedGoal}`);

  await page.addInitScript(() => localStorage.setItem('mc_proto_wizard_done_v1', '1'));
  const results = [];

  for (const [name, path, text] of routes) {
    await page.goto(urlFor(path), { waitUntil: 'networkidle' });
    await page.waitForSelector(`text=${text}`, { timeout: 10000 });
    results.push({ name, path, ok: true, title: await page.title() });
  }

  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.getByText('示例快照', { exact: true }).waitFor({ timeout: 10000 });
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
  await page.screenshot({ path: path.join(shotsDir, 'v2-home-terminal.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileResults = [];
  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.waitForSelector('text=明仓终端', { timeout: 10000 });
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(shotsDir, 'v2-mobile-home-terminal.png'), fullPage: true });
  for (const [name, path, text] of routes.filter(([name]) => !name.includes('legacy'))) {
    await page.goto(urlFor(path), { waitUntil: 'networkidle' });
    await page.waitForSelector(`text=${text}`, { timeout: 10000 });
    const navVisible = await page.locator('.navlinks').isVisible();
    const statusVisible = await page.locator('.nav-status').isVisible();
    const mobileLabelVisible = await page.getByText('页面导航', { exact: true }).isVisible();
    const activeLinks = await page.locator('.navlink[aria-current="page"]').count();
    const viewportFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    if (!navVisible || !statusVisible || !mobileLabelVisible || activeLinks !== 1 || !viewportFits) {
      throw new Error(`mobile navigation failed on ${path}: ${JSON.stringify({ navVisible, statusVisible, mobileLabelVisible, activeLinks, viewportFits })}`);
    }
    mobileResults.push({ name: `${name}-mobile`, path, ok: true });
  }
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(shotsDir, 'v2-mobile-memory.png'), fullPage: true });

  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    document.body.tabIndex = -1;
    document.body.focus();
  });
  await page.keyboard.press('Tab');
  const skipFocused = await page.evaluate(() => document.activeElement?.classList.contains('skip-link'));
  await page.evaluate(() => document.body.removeAttribute('tabindex'));
  if (!skipFocused) throw new Error('keyboard focus should start at the skip link');

  let coverageFails = false;
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/system/data-coverage') && coverageFails) {
      // A syntactically broken payload exercises the rejected-domain path
      // without creating an expected 5xx console error that would mask UI errors.
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{' });
      return;
    }
    let body = {};
    if (url.pathname.endsWith('/watchlist') || url.pathname.endsWith('/positions') || url.pathname.endsWith('/reviews') || url.pathname.endsWith('/ai/sessions')) body = [];
    else if (url.pathname.endsWith('/memory/list')) body = { rows: [] };
    else if (url.pathname.endsWith('/system/data-coverage')) body = { checks: {}, warnings: [], stocks: [], provider_fallback_chains: { chains_by_market: {} } };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.getByText('本地后端', { exact: true }).waitFor({ timeout: 10000 });
  results.push({ name: 'live-source-truth', path: '/', ok: true });

  coverageFails = true;
  await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
  await page.getByText('部分实时', { exact: true }).waitFor({ timeout: 10000 });
  results.push({ name: 'partial-live-source-truth', path: '/', ok: true });

  await browser.close();
  if (staticServer) await new Promise((resolve) => staticServer.close(resolve));

  const payload = { results, mobileResults, consoleErrors, pageErrors };
  console.log(JSON.stringify(payload, null, 2));
  if (consoleErrors.length || pageErrors.length) process.exit(1);
})();
