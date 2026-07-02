export const RESEARCH_REPORT_PACK_SCHEMA = 'research_report_pack.v1' as const;

export type ReportGateStatus = 'pass' | 'warning' | 'blocked' | 'gate_disabled' | string;

export interface EvidenceLedgerEntry {
  title: string;
  source: string;
  published_at: string;
  score: number;
  usable: boolean;
  risk_flags: string[];
  duplicate_group: string;
  tier?: string;
}

export interface PackSection {
  number: number;
  heading: string;
  body: string;
}

export interface ResearchReportPack {
  schema_version: typeof RESEARCH_REPORT_PACK_SCHEMA;
  topic: string;
  symbols: string[];
  as_of: string;
  gate_status: ReportGateStatus;
  gate_reasons: string[];
  blocked: boolean;
  evidence_ledger: EvidenceLedgerEntry[];
  body_sections: PackSection[];
  observe_only: boolean;
  signal_impact: string;
  not_a_buy_score: boolean;
}

export const PACK_SECTION_HEADINGS: PackSection[] = [
  { number: 1, heading: '一、执行摘要 Executive Brief', body: '' },
  { number: 2, heading: '二、正方/反方论点 Thesis / Anti-Thesis', body: '' },
  { number: 3, heading: '三、证据台账 Evidence Ledger', body: '' },
  { number: 4, heading: '四、财务/行业/新闻/技术模块 Financial / Industry / News / Technical Blocks', body: '' },
  { number: 5, heading: '五、风险触发器 Risk Triggers', body: '' },
  { number: 6, heading: '六、同业/供应链 Peer / Supply Chain', body: '' },
  { number: 7, heading: '七、验证问题 Validation Questions', body: '' },
  { number: 8, heading: '八、复盘挂钩 ReviewCase Hook', body: '' },
  { number: 9, heading: '九、报告头部元数据 Report Header Metadata', body: '' },
];

const PLACEHOLDER = '无数据 / not available';
const DISCLAIMER = '本报告包为 observe-only 研究产物，不构成投资建议，不自动影响生产信号、仓位或交易。';

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' ? value as Record<string, any> : {};
}

function asString(value: unknown, fallback = ''): string {
  if (value === null || value === undefined) return fallback;
  return String(value);
}

function asStringList(value: unknown): string[] {
  return asArray(value).map((item) => String(item)).filter(Boolean);
}

function asNumber(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function isPlaceholder(body: string): boolean {
  return !body.trim() || body.trim() === PLACEHOLDER;
}

function normalizeEvidenceEntry(value: unknown, index: number): EvidenceLedgerEntry {
  const entry = asRecord(value);
  const source = asString(entry.source || entry.source_name || entry.tier, '未知来源');
  const title = asString(entry.title || entry.headline || source);
  const tier = entry.tier || entry.source_tier;
  return {
    title,
    source,
    published_at: asString(entry.published_at || entry.fetched_at || entry.date),
    score: asNumber(entry.score, entry.usable === false ? 40 : 100),
    usable: entry.usable !== false,
    risk_flags: asStringList(entry.risk_flags),
    duplicate_group: asString(entry.duplicate_group, `${source}-${index}`),
    ...(tier ? { tier: String(tier) } : {}),
  };
}

function normalizeSections(sections: unknown, blocked: boolean): PackSection[] {
  if (blocked) return [];
  const incoming = asArray(sections).map((value) => {
    const section = asRecord(value);
    return {
      number: asNumber(section.number),
      heading: asString(section.heading),
      body: asString(section.body, PLACEHOLDER),
    };
  });
  return PACK_SECTION_HEADINGS.map((expected) => {
    const found = incoming.find((section) => section.number === expected.number);
    return {
      number: expected.number,
      heading: found?.heading || expected.heading,
      body: found?.body || PLACEHOLDER,
    };
  });
}

function isPackLike(value: unknown): boolean {
  return asRecord(value).schema_version === RESEARCH_REPORT_PACK_SCHEMA;
}

function normalizePack(value: unknown): ResearchReportPack {
  const pack = asRecord(value);
  const gateStatus = asString(pack.gate_status, 'gate_disabled');
  const blocked = Boolean(pack.blocked || gateStatus === 'blocked');
  return {
    schema_version: RESEARCH_REPORT_PACK_SCHEMA,
    topic: asString(pack.topic),
    symbols: asStringList(pack.symbols),
    as_of: asString(pack.as_of),
    gate_status: gateStatus,
    gate_reasons: asStringList(pack.gate_reasons),
    blocked,
    evidence_ledger: asArray(pack.evidence_ledger).map(normalizeEvidenceEntry),
    body_sections: normalizeSections(pack.body_sections, blocked),
    observe_only: pack.observe_only !== false,
    signal_impact: asString(pack.signal_impact, 'none'),
    not_a_buy_score: pack.not_a_buy_score !== false,
  };
}

function evidenceBody(entries: EvidenceLedgerEntry[]): string {
  if (!entries.length) return PLACEHOLDER;
  return entries.map((entry) => {
    const flags = entry.risk_flags.length ? entry.risk_flags.join('、') : '无风险标记';
    const tier = entry.tier ? ` | 层级：${entry.tier}` : '';
    return `- [${entry.usable ? '可用' : '不可用'}] ${entry.title}\n  来源：${entry.source}${tier} | 发布：${entry.published_at || '未知日期'} | 评分：${entry.score} | 风险：${flags}`;
  }).join('\n');
}

function thesisBody(report: Record<string, any>): string {
  const lines: string[] = [];
  asArray(report.sections).forEach((value) => {
    const section = asRecord(value);
    const role = asString(section.role || section.title, '研究分段');
    const content = asString(section.content);
    const catalysts = asStringList(section.catalysts);
    const risks = asStringList(section.risks);
    lines.push(`**${role}**`);
    if (content) lines.push(content);
    if (catalysts.length) lines.push(`催化剂：${catalysts.join('；')}`);
    if (risks.length) lines.push(`风险：${risks.join('；')}`);
  });
  return lines.length ? lines.join('\n') : PLACEHOLDER;
}

function listBody(items: string[], prefix = '- '): string {
  if (!items.length) return PLACEHOLDER;
  return items.map((item, index) => prefix.includes('{n}') ? prefix.replace('{n}', String(index + 1)) + item : `${prefix}${item}`).join('\n');
}

function metadataBody(report: Record<string, any>, evidence: EvidenceLedgerEntry[]): string {
  const usable = evidence.filter((entry) => entry.usable).length;
  const lines = [
    `主题：${asString(report.topic || report.title, '研究报告')}`,
    `标的：${asStringList(report.symbols).join(', ') || '（纯主题，无指定标的）'}`,
    `研究日期：${asString(report.as_of, '未知')}`,
    `来源数量：${asNumber(report.source_count, evidence.length)}`,
    `可用证据：${usable}/${evidence.length}`,
    `门控状态：${asString(report.gate_status, 'gate_disabled')}`,
    `schema：${RESEARCH_REPORT_PACK_SCHEMA}`,
  ];
  const reasons = asStringList(report.gate_reasons);
  if (reasons.length) {
    lines.push('门控原因：');
    reasons.forEach((reason) => lines.push(`  - ${reason}`));
  }
  return lines.join('\n');
}

function legacyPack(report: Record<string, any>): ResearchReportPack {
  const gateStatus = asString(report.gate_status, 'gate_disabled');
  const blocked = Boolean(report.blocked || gateStatus === 'blocked');
  const evidence = asArray(report.audits).map(normalizeEvidenceEntry);
  const falsification = asStringList(report.falsification);
  const bodySections = blocked ? [] : [
    { number: 1, heading: PACK_SECTION_HEADINGS[0].heading, body: asString(report.summary || report.topic || report.title, PLACEHOLDER) },
    { number: 2, heading: PACK_SECTION_HEADINGS[1].heading, body: thesisBody(report) },
    { number: 3, heading: PACK_SECTION_HEADINGS[2].heading, body: evidenceBody(evidence) },
    { number: 4, heading: PACK_SECTION_HEADINGS[3].heading, body: asString(report.content, PLACEHOLDER) },
    { number: 5, heading: PACK_SECTION_HEADINGS[4].heading, body: listBody(falsification) },
    { number: 6, heading: PACK_SECTION_HEADINGS[5].heading, body: PLACEHOLDER },
    { number: 7, heading: PACK_SECTION_HEADINGS[6].heading, body: listBody(falsification, '{n}. 验证：') },
    { number: 8, heading: PACK_SECTION_HEADINGS[7].heading, body: PLACEHOLDER },
    { number: 9, heading: PACK_SECTION_HEADINGS[8].heading, body: metadataBody(report, evidence) },
  ];
  return {
    schema_version: RESEARCH_REPORT_PACK_SCHEMA,
    topic: asString(report.topic || report.title, '研究报告'),
    symbols: asStringList(report.symbols),
    as_of: asString(report.as_of),
    gate_status: gateStatus,
    gate_reasons: asStringList(report.gate_reasons),
    blocked,
    evidence_ledger: evidence,
    body_sections: bodySections,
    observe_only: true,
    signal_impact: 'none',
    not_a_buy_score: true,
  };
}

export function toResearchReportPack(report: unknown): ResearchReportPack {
  const value = asRecord(report);
  if (isPackLike(value)) return normalizePack(value);
  if (isPackLike(value.report_pack)) return normalizePack(value.report_pack);
  return legacyPack(value);
}

export function packBodyCoverage(pack: ResearchReportPack) {
  const sections = pack.body_sections;
  const populated = sections.filter((section) => !isPlaceholder(section.body)).length;
  return {
    total: pack.blocked ? PACK_SECTION_HEADINGS.length : sections.length,
    populated,
    placeholders: sections.length - populated,
  };
}

export function packToMarkdown(pack: ResearchReportPack): string {
  const symbols = pack.symbols.length ? pack.symbols.join(', ') : '（纯主题，无指定标的）';
  const lines = [
    `# ${pack.topic || '研究报告包'} — 研究报告包 v1`,
    '',
    `- 标的：${symbols}`,
    `- 研究日期：${pack.as_of || '未知'}`,
    `- 门控状态：${pack.gate_status}`,
    `- schema：${pack.schema_version}`,
    `- observe_only：${pack.observe_only}`,
    `- signal_impact：${pack.signal_impact}`,
    `- not_a_buy_score：${pack.not_a_buy_score}`,
    '',
  ];
  if (pack.gate_reasons.length) {
    lines.push('## Gate Metadata', '');
    pack.gate_reasons.forEach((reason) => lines.push(`- ${reason}`));
    lines.push('');
  }
  if (pack.blocked) {
    lines.push('> 报告被门控阻断（blocked）——正文不予导出。', '', `_${DISCLAIMER}_`);
    return lines.join('\n');
  }
  pack.body_sections.forEach((section) => {
    lines.push(`## ${section.heading}`, '', section.body || PLACEHOLDER, '');
  });
  lines.push(`_${DISCLAIMER}_`);
  return lines.join('\n');
}
