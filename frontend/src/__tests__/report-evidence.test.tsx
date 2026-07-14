import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EvidenceCard } from '../page-reports';
import { toResearchReportPack } from '../report-pack';

describe('research evidence card', () => {
  it('keeps publication time distinct from fetch time and exposes unknowns', () => {
    const pack = toResearchReportPack({
      topic: '测试主题',
      as_of: '2026-07-15',
      audits: [{
        title: '公告摘要',
        source: '巨潮资讯',
        source_tier: 'official',
        fetched_at: '2026-07-14T10:00:00+08:00',
        risk_flags: [],
      }],
    });

    const evidence = pack.evidence_ledger[0];
    expect(evidence.published_at).toBe('');
    expect(evidence.fetched_at).toBe('2026-07-14T10:00:00+08:00');
    expect(evidence.published_at).not.toBe(evidence.fetched_at);
    expect(evidence.as_of).toBe('2026-07-15');
    expect(evidence.freshness_status).toBe('unknown');
    expect(evidence.tier).toBe('official');
    expect(evidence.usable_known).toBe(false);
    expect(evidence.missing_reason).toContain('发布时间未提供');
    expect(evidence.missing_reason).toContain('可用性未提供');
  });

  it('renders provenance, freshness, risk and missing fields explicitly', () => {
    const entry = toResearchReportPack({
      schema_version: 'research_report_pack.v1',
      topic: '测试主题',
      as_of: '2026-07-15',
      evidence_ledger: [{
        title: '公告原文',
        source: '交易所',
        source_tier: 'official',
        published_at: '2026-07-13T09:00:00+08:00',
        fetched_at: '2026-07-13T10:00:00+08:00',
        freshness_status: 'fresh',
        usable: true,
        risk_flags: ['partial_content'],
        missing_reason: '正文页码未提供',
      }],
    }).evidence_ledger[0];

    render(<EvidenceCard entry={entry} />);

    expect(screen.getByText('官方')).toBeInTheDocument();
    expect(screen.getByText('新鲜度 fresh')).toBeInTheDocument();
    expect(screen.getByText('可用')).toBeInTheDocument();
    expect(screen.getByText(/发布时间：2026-07-13T09:00:00/)).toBeInTheDocument();
    expect(screen.getByText(/抓取时间：2026-07-13T10:00:00/)).toBeInTheDocument();
    expect(screen.getByText(/证据截止：2026-07-15/)).toBeInTheDocument();
    expect(screen.getByText('风险标记：partial_content')).toBeInTheDocument();
    expect(screen.getByText('缺失/未知：正文页码未提供')).toBeInTheDocument();
  });
});
