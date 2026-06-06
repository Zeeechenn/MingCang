<section class="mc-hero">
  <div class="mc-hero__copy">
    <p class="mc-kicker">Local-first stock research workbench</p>
    <h1>明仓，把股票研究做成可复盘的证据循环。</h1>
    <p class="mc-hero__lead">
      明仓把自选、行情、新闻、官方信号、AI 研究、长期论题、复盘和记忆放进同一个本地工作台。它不自动下单，不接券商，也不让 LLM 替你买卖；它帮助你把每一次判断留下证据、边界和复盘线索。
    </p>
    <div class="mc-actions">
      <a class="mc-button mc-button--primary" href="USER_GUIDE/">开始使用</a>
      <a class="mc-button mc-button--secondary" href="FEATURE_MAP/">查看全部功能</a>
      <a class="mc-button mc-button--secondary" href="WHY_NOT_AI_STOCK_PICKER/">先看安全边界</a>
    </div>
    <div class="mc-signal-row" aria-label="MingCang principles">
      <div class="mc-signal">
        <strong>本地优先</strong>
        <span>数据、记忆和确认动作留在你的机器上</span>
      </div>
      <div class="mc-signal">
        <strong>证据优先</strong>
        <span>信号、研究、新闻和复盘可追溯</span>
      </div>
      <div class="mc-signal">
        <strong>确认优先</strong>
        <span>写入和高风险动作必须显式确认</span>
      </div>
    </div>
  </div>
</section>

<div class="mc-section-head">
  <div>
    <h2>第一次打开，按任务进文档</h2>
  </div>
  <p>这套文档不是一本从头读到尾的手册。它按你要完成的研究任务组织：先跑 demo，再研究一只股票，再理解全部功能和系统边界。</p>
</div>

<div class="mc-grid mc-grid--routes">
  <a class="mc-card mc-card--wide mc-card--dark" href="USER_GUIDE/">
    <span class="mc-meta">开始路径</span>
    <h3>从 demo 到第一只股票</h3>
    <p>跑 <code>make demo</code>，打开本地前端，查看自选、单股详情、复盘和记忆候选。适合第一次判断“明仓到底能做什么”。</p>
    <div class="mc-command">
      <div><span>$</span> make demo</div>
      <div><span>$</span> mingcang stock 300308</div>
      <div><span>$</span> mingcang project</div>
    </div>
  </a>
  <div class="mc-card">
    <span class="mc-meta">文档地图</span>
    <h3>文档怎么读</h3>
    <div class="mc-mini-list">
      <div class="mc-mini">
        <strong>User Guide</strong>
        <span>单股研究、每日扫描、专题研究、复盘记忆。</span>
      </div>
      <div class="mc-mini">
        <strong>Feature Map</strong>
        <span>所有功能逐项说明：入口、状态、写入、信号和 key。</span>
      </div>
      <div class="mc-mini">
        <strong>Reference</strong>
        <span>前端页面、后端 API、CLI、action、配置。</span>
      </div>
    </div>
  </div>
</div>

<div class="mc-section-head">
  <div>
    <h2>核心研究闭环</h2>
  </div>
  <p>明仓不是“AI 荐股器”，而是一套研究流程：提出问题，收集证据，形成可审计判断，复盘偏差，再把值得保留的经验沉淀为记忆。</p>
</div>

<div class="mc-flow">
  <div class="mc-step">
    <span>01</span>
    <strong>自选</strong>
    <p>管理关注标的和候选池，从脉冲页进入单股研究。</p>
  </div>
  <div class="mc-step">
    <span>02</span>
    <strong>证据</strong>
    <p>聚合行情、新闻、情绪、长期标签和记忆上下文。</p>
  </div>
  <div class="mc-step">
    <span>03</span>
    <strong>信号</strong>
    <p>技术、情绪和风控聚合为官方建议，量化当前为影子路径。</p>
  </div>
  <div class="mc-step">
    <span>04</span>
    <strong>研究</strong>
    <p>LLM 负责整理、反问、辩论和风险提示，不覆盖官方信号。</p>
  </div>
  <div class="mc-step">
    <span>05</span>
    <strong>复盘</strong>
    <p>用 ReviewCase 归因，人工确认后再升级为可信记忆。</p>
  </div>
</div>

<div class="mc-section-head">
  <div>
    <h2>功能按能力分组</h2>
  </div>
  <p>如果你想快速判断“明仓到底有哪些模块”，从下面几组进入。每一组在 Feature Map 里都有逐项功能说明。</p>
</div>

<div class="mc-grid mc-grid--features">
  <a class="mc-card" href="FEATURE_MAP/">
    <span class="mc-meta">Research</span>
    <h3>单股研究、专题研究和 LLM 辩论</h3>
    <p>Research State、Dossier、Copilot、Deep Research、多空辩论、Research Director、ForwardThesis。</p>
  </a>
  <a class="mc-card" href="FEATURE_MAP/">
    <span class="mc-meta">Signal</span>
    <h3>官方信号、风控和计算公式</h3>
    <p>技术信号、新闻情绪、信号聚合、ATR 止损、trailing stop、仓位上限、kill switch。</p>
  </a>
  <a class="mc-card" href="FEATURE_MAP/">
    <span class="mc-meta">Memory</span>
    <h3>复盘记忆和长期经验沉淀</h3>
    <p>AI Memory、Stock Memory、L0 Atoms、Memory Context、Promotion Candidate、Audit Log。</p>
  </a>
  <a class="mc-card" href="FEATURE_MAP/">
    <span class="mc-meta">Data</span>
    <h3>行情、新闻、财务和数据源健康</h3>
    <p>A 股行情、新闻抓取、情绪缓存、财务指标、QFII、provider registry、global data。</p>
  </a>
  <a class="mc-card" href="FEATURE_MAP/">
    <span class="mc-meta">Quant</span>
    <h3>量化验证和影子证据</h3>
    <p>Qlib、Kronos、回测、M29 shadow evidence、PIT guard、universe guard；默认不进正式信号。</p>
  </a>
  <a class="mc-card" href="REFERENCE/">
    <span class="mc-meta">System</span>
    <h3>前端、后台、CLI 和 agent 接口</h3>
    <p>脉冲页、单股页、复盘页、持仓页、聊天页、配置页、FastAPI、Action Registry、MCP server。</p>
  </a>
</div>

<div class="mc-callout">
  <p><strong>安全边界：</strong>明仓可以帮助你研究、记录、证伪、复盘和沉淀经验；它不会自动交易，不会替你做最终投资决定，也不会把 LLM 输出当成正式买卖信号。</p>
</div>

<div class="mc-section-head">
  <div>
    <h2>继续阅读</h2>
  </div>
  <p>按你当前的目的选入口。普通用户先读 User Guide；想看全貌再进 Feature Map；开发者再看 Reference 和 Developer Guide。</p>
</div>

<div class="mc-doc-list">
  <a class="mc-doc-link" href="USER_GUIDE/">
    <span><strong>User Guide</strong><br>任务型手册：demo、单股研究、每日扫描、专题研究、复盘记忆。</span>
    <span>打开</span>
  </a>
  <a class="mc-doc-link" href="FEATURE_MAP/">
    <span><strong>Feature Map</strong><br>功能模块地图：默认启用、只读、影子、休眠、写入和 key。</span>
    <span>打开</span>
  </a>
  <a class="mc-doc-link" href="ARCHITECTURE/">
    <span><strong>Architecture</strong><br>研究闭环、证据对象、记忆促进和安全确认模型。</span>
    <span>打开</span>
  </a>
  <a class="mc-doc-link" href="DEVELOPER_GUIDE/">
    <span><strong>Developer Guide</strong><br>后续开发：加页面、API、action、研究模块、量化模块。</span>
    <span>打开</span>
  </a>
</div>

<div class="mc-footer-panel">
  <p class="mc-muted">公开站点只从 `docs_public/` 构建。内部路线图、历史研究、评审和开发归档仍留在仓库内部文档区，不作为普通用户入口。</p>
</div>
