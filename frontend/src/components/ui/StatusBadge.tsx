import type { ReactNode } from 'react'

import Badge from './Badge.jsx'

export type StatusBadgeStatus =
  | 'pass'
  | 'warning'
  | 'blocked'
  | 'bull'
  | 'bear'
  | 'watch'
  | 'neutral'
  | 'info'

const TONE_BY_STATUS: Record<StatusBadgeStatus, string> = {
  pass: 'bear',
  warning: 'amber',
  blocked: 'bull',
  bull: 'bull',
  bear: 'bear',
  watch: 'watch',
  neutral: 'neutral',
  info: 'cyan',
}

const LABEL_BY_STATUS: Record<StatusBadgeStatus, string> = {
  pass: '通过',
  warning: '需复核',
  blocked: '阻断',
  bull: '偏多',
  bear: '偏空',
  watch: '观察',
  neutral: '中性',
  info: '信息',
}

interface StatusBadgeProps {
  status?: StatusBadgeStatus
  className?: string
  children?: ReactNode
}

export default function StatusBadge({
  status = 'neutral',
  className = '',
  children,
}: StatusBadgeProps) {
  return (
    <Badge tone={TONE_BY_STATUS[status]} className={className}>
      {children || LABEL_BY_STATUS[status]}
    </Badge>
  )
}
