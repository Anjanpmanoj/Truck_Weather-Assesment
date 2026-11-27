import type { RiskKey } from '../types/route'

// One source of truth for risk colors; the map and heatmap reuse it.
export const RISK_ORDER: RiskKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel', 'unknown']

export const RISK_META: Record<RiskKey, { label: string; color: string }> = {
  low: { label: 'Low', color: '#22c55e' },
  moderate: { label: 'Moderate', color: '#eab308' },
  high: { label: 'High', color: '#f97316' },
  severe: { label: 'Severe', color: '#ef4444' },
  no_travel: { label: 'No Travel', color: '#c026d3' },
  unknown: { label: 'Unknown', color: '#64748b' },
}

// The API's numeric risk value (0 to 4) in order; null means unknown.
const KEY_BY_VALUE: RiskKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel']

export function riskKeyFromValue(value: number | null): RiskKey {
  return value === null ? 'unknown' : (KEY_BY_VALUE[value] ?? 'unknown')
}