import {
  getDataCoverage as getDataCoverageRaw,
  getLatestSignal as getLatestSignalRaw,
  getPositions as getPositionsRaw,
  getReview as getReviewRaw,
  getReviews as getReviewsRaw,
  getSignalEvidence as getSignalEvidenceRaw,
  getSignals as getSignalsRaw,
} from './api'
import type {
  DataCoverageOut,
  DecisionRunOut,
  PositionOut,
  ReviewRunOut,
  SignalOut,
} from './apiTypes'

export const getTypedLatestSignal = getLatestSignalRaw as (symbol: string) => Promise<SignalOut>
export const getTypedSignals = getSignalsRaw as (symbol: string, limit?: number) => Promise<SignalOut[]>
export const getTypedSignalEvidence = getSignalEvidenceRaw as (
  symbol: string,
  limit?: number,
) => Promise<DecisionRunOut[]>
export const getTypedPositions = getPositionsRaw as (status?: string) => Promise<PositionOut[]>
export const getTypedReviews = getReviewsRaw as (kind?: string) => Promise<ReviewRunOut[]>
export const getTypedReview = getReviewRaw as (id: number) => Promise<ReviewRunOut>
export const getTypedDataCoverage = getDataCoverageRaw as () => Promise<DataCoverageOut>
