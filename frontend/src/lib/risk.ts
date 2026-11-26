import type { RiskKey } from '../types/route'

// One source of truth for risk colors; the map and heatmap will reuse it.
export const RISK_ORDER: RiskKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel', 'unknown']

export const RISK_META: Record<RiskKey, { label: string; color: string }> = {
  low: { label: 'Low', color: '#22c55e' },
  moderate: { label: 'Moderate', color: '#eab308' },
  high: { label: 'High', color: '#f97316' },
  severe: { label: 'Severe', color: '#ef4444' },
  no_travel: { label: 'No Travel', color: '#c026d3' },
  unknown: { label: 'Unknown', color: '#64748b' },
}