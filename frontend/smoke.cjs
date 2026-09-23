const { chromium } = require('playwright');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const smokePort = Number(process.env.MC_SMOKE_PORT || 4174);
const baseUrl = process.env.MC_SMOKE_BASE_URL || `http://127.0.0.1:${smokePort}`;
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
  await new Promise((resolve) => staticServer.listen(smokePort, '127.0.0.1', resolve));
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
  let dailyPanelFixture = null;
  let dailyReviewFixture = { items: [], history: [], history_limit: 100, warning: null };
  const crypto = require('node:crypto');
  let researchReviews = [];
  let researchMessages = [];
  const researchContext = selection => ({ selection, context_sha256: crypto.createHash('sha256').update(JSON.stringify(selection)).digest('hex'),
    sources: [{ id: 'price-1', kind: 'price', source: 'browser-fixture', date: selection.as_of, adjustment: 'qfq', currency: 'CNY', fetched_at: null, values: { close: 11 } }],
    gaps: [], limitations: ['浏览器合成资料，非真实研究'], can_ask: true });
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/system/data-coverage') && coverageFails) {
      // A syntactically broken payload exercises the rejected-domain path
      // without creating an expected 5xx console error that would mask UI errors.
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{' });
      return;
    }
    if (url.pathname.endsWith('/page-context')) {
      const selection = Object.fromEntries(url.searchParams);
      const value = researchContext(selection);
      await route.fulfill({ json: value }); return;
    }
    if (url.pathname.endsWith('/ai/chat/stream')) {
      const req = route.request().postDataJSON(); const selection = { ...req.research_context }; delete selection.context_sha256;
      const snapshot = researchContext(selection);
      const value = { answer: '合成回答：现金流仍待核验。', research_context: req.research_context, session_id: 'research-smoke',
        research_claims: [{ text: '合成回答：现金流仍待核验。', evidence_ids: ['price-1'] }] };
      researchMessages.push({ role: 'user', context_snapshot: snapshot }, { role: 'assistant', ...value });
      await route.fulfill({ contentType: 'text/event-stream', body: `event: done\ndata: ${JSON.stringify(value)}\n\n` }); return;
    }
    if (url.pathname.endsWith('/ai/sessions/research-smoke/messages')) { await route.fulfill({ json: researchMessages }); return; }
    if (url.pathname.endsWith('/page-reviews')) {
      if (route.request().method() === 'POST') {
        const req = route.request().postDataJSON(); const selection = { ...req.context }; delete selection.context_sha256;
        const record = { review_id: 'research-smoke-review', source: researchContext(selection),
          result: { version: 1, decision: req, outcomes: [] } };
        researchReviews = [record]; await route.fulfill({ json: record }); return;
      }
      await route.fulfill({ json: { reviews: researchReviews } }); return;
    }
    if (url.pathname.includes('/research/page-reviews/') && url.pathname.endsWith('/outcomes')) {
      const req = route.request().postDataJSON(); const record = researchReviews[0];
      record.result.outcomes.push({ ...req, recorded_at: '2026-09-17T00:00:00Z' }); record.result.version++;
      await route.fulfill({ json: record }); return;
    }
    let body = {};
    if (url.pathname.endsWith('/watchlist') || url.pathname.endsWith('/positions') || url.pathname === '/api/reviews' || url.pathname.endsWith('/ai/sessions')) body = [];
    else if (url.pathname.endsWith('/memory/list')) body = { rows: [] };
    // runtime identity 门：live 模式要求 /system/status 返回兼容的运行身份
    else if (url.pathname.endsWith('/system/status')) body = { version: require('./package.json').version, build_commit: 'unknown', db_role: 'primary', db_latest_date: '2026-07-16', scheduler_mode: 'manual', database_exists: true };
    else if (url.pathname.endsWith('/daily/reviews')) body = dailyReviewFixture;
    else if (url.pathname.endsWith('/daily/panel/latest') && dailyPanelFixture) body = dailyPanelFixture;
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

  coverageFails = false;
  const dailyTypes = ['batch_integrity', 'candidate', 'position_health', 'event_risk', 'watchtower', 'daily_delta', 'human_confirmation', 'review_attribution'];
  dailyPanelFixture = {
    schema_version: 'daily_panel.v1', mode: 'postmarket', as_of: '2026-09-16', status: 'ready',
    lifecycle_visibility: { stable: dailyTypes.filter(x => !['event_risk', 'watchtower'].includes(x)), shadow: ['event_risk', 'watchtower'] },
    cards: dailyTypes.map(card_type => ({
      card_type, lifecycle: ['event_risk', 'watchtower'].includes(card_type) ? 'shadow' : 'stable',
      status: card_type === 'event_risk' ? 'not_applicable' : card_type === 'watchtower' ? 'degraded' : 'ready',
      summary: '浏览器验证用合成面板',
      payload: card_type === 'event_risk' ? { reason: '本次关闭 LLM，不能解释为没有事件风险。' }
        : card_type === 'watchtower' ? { reason: '扫描覆盖不完整，保留已发现线索。', followups: { coverage: { price_gaps: { '600002': ['stale_price'] }, fund_flow_gaps: { '600003': 'missing_as_of' } } } }
        : card_type === 'daily_delta' ? { reason: '比较已提交面板名单。', structured_delta: { current_as_of: '2026-09-16', previous_as_of: '2026-09-15', candidate_added: ['600001'] } }
        : card_type === 'human_confirmation' ? { queue_stale_count: 3 } : {},
      evidence_refs: [], run_ref: { run_id: 'browser-fixture', status: 'complete' },
      drilldown: { kind: 'none', href: null, label: '' },
    })),
  };
  dailyReviewFixture = {
    panel_as_of: '2026-09-16', panel_sha256: 'b'.repeat(64), warning: null, history: [], history_limit: 100,
    summary: { current: 1, historical: 1, unverified: 0, recorded_choices: 0, with_observations: 0, independently_verified_outcomes: null },
    items: [['current', '本期合成研究', '2026-09-16'], ['historical', '历史合成研究', '2026-07-05']].map(([source_scope, summary, source_date]) => ({
      item_id: source_scope, panel_as_of: '2026-09-16', panel_sha256: 'b'.repeat(64), run_id: 'browser-fixture',
      card_type: 'human_confirmation', subject: '600001', name: summary, summary, original: { created_at: source_date },
      source_scope, source_date, expires_at: null, validity: 'unknown', source_status: 'ready', reviewable: true, review: null,
    })),
  };
  for (const [label, width, height] of [['desktop', 1440, 960], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.goto(urlFor('/#/daily'), { waitUntil: 'networkidle' });
    await page.getByText('本次关闭 LLM，不能解释为没有事件风险。', { exact: true }).waitFor();
    await page.getByText('扫描覆盖不完整，保留已发现线索。', { exact: true }).waitFor();
    await page.getByText('新增候选：600001', { exact: true }).waitFor();
    await page.getByText('3 项来自历史交易日，仍待人工处理；未回复的事项继续保留。', { exact: true }).waitFor();
    if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)) throw new Error('daily reason overflow');
    await page.getByText(/行情待补 1 项，资金流待补 1 项/).waitFor();
    await page.getByLabel('资料范围').waitFor();
    await page.getByLabel('资料范围').selectOption('current');
    await page.getByRole('article', { name: '研究待办 本期合成研究' }).waitFor();
    if (await page.getByRole('article', { name: '研究待办 历史合成研究' }).count()) throw new Error('historical item leaked into current filter');
    await page.getByLabel('资料范围').selectOption('historical');
    await page.getByRole('article', { name: '研究待办 历史合成研究' }).waitFor();
    if (await page.getByRole('article', { name: '研究待办 本期合成研究' }).count()) throw new Error('current filter did not switch');
    if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)) throw new Error('review period overflow');
    await page.screenshot({ path: path.join(shotsDir, `daily-sources-${label}.png`), fullPage: true });
    results.push({ name: `daily-sources-${label}`, path: '/#/daily', ok: true });
  }

  coverageFails = false;
  for (const [label, width, height] of [['desktop', 1440, 960], ['mobile', 390, 844]]) {
    researchReviews = []; researchMessages = [];
    await page.goto(urlFor('/'), { waitUntil: 'networkidle' });
    await page.evaluate(() => localStorage.removeItem('mc_research_session_300308'));
    await page.setViewportSize({ width, height });
    await page.goto(urlFor('/#/stock/CN/300308'), { waitUntil: 'networkidle' });
    await page.getByLabel('证据截止日').fill('2026-09-15');
    await page.getByLabel('证据起始日').fill('2026-09-01');
    await page.getByRole('button', { name: '基于这些证据提问' }).waitFor();
    await page.getByLabel('本页研究问题').fill('现金流还缺什么资料？');
    await page.getByRole('button', { name: '基于这些证据提问' }).click();
    await page.getByText('合成回答：现金流仍待核验。', { exact: true }).waitFor();
    await page.getByLabel('证据截止日').fill('2026-09-14');
    await page.getByText(/不适用于当前选择/).waitFor();
    await page.getByLabel('我的判断').fill(`合成观察 ${label}`);
    await page.getByLabel('判断依据').fill('现金流仍缺核验');
    await page.getByLabel('后续验证条件').fill('等待新公告');
    await page.getByRole('button', { name: '保存判断与证据' }).click();
    await page.getByText(`2026-09-14 · 合成观察 ${label}`, { exact: true }).click();
    await page.getByLabel('观察依据').fill('新公告尚未发布');
    await page.getByRole('button', { name: '追加观察' }).click();
    await page.getByText('新公告尚未发布', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(shotsDir, `research-context-${label}.png`), fullPage: true });
    await page.locator('section').filter({ has: page.getByRole('heading', { name: '基于本页证据研究' }) }).screenshot({ path: path.join(shotsDir, `research-workspace-${label}.png`) });
    if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)) throw new Error('research context overflow');
    await page.reload({ waitUntil: 'networkidle' });
    await page.getByText(`2026-09-14 · 合成观察 ${label}`, { exact: true }).click();
    await page.getByText('新公告尚未发布', { exact: true }).waitFor();
    await page.getByText('合成回答：现金流仍待核验。', { exact: true }).waitFor();
    results.push({ name: `research-context-${label}`, path: '/#/stock/CN/300308', ok: true });
  }

  await browser.close();
  if (staticServer) await new Promise((resolve) => staticServer.close(resolve));

  const payload = { results, mobileResults, consoleErrors, pageErrors };
  console.log(JSON.stringify(payload, null, 2));
  if (consoleErrors.length || pageErrors.length) process.exit(1);
})();
