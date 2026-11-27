import type { Checkpoint, CorridorPoint } from '../types/route'
import { formatDateTime, formatForecastTime } from './format'
import { RISK_META, riskKeyFromValue } from './risk'

function el(tag: keyof HTMLElementTagNameMap, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function reading(value: number | null, unit: string): string {
  return value === null ? '–' : `${value} ${unit}`
}

function badge(label: string, color: string): HTMLElement {
  const node = el('span', 'inline-block rounded-full border px-2 py-0.5 font-medium', label)
  node.style.color = color
  node.style.borderColor = color
  node.style.backgroundColor = `${color}1a`
  return node
}

function grid(rows: [string, string][]): HTMLElement {
  const list = el('dl', 'grid grid-cols-2 gap-x-4 gap-y-1.5')
  for (const [label, value] of rows) {
    const cell = el('div', '')
    cell.append(el('dt', 'text-slate-500', label), el('dd', 'font-medium text-slate-100', value))
    list.append(cell)
  }
  return list
}

// Built with textContent (not HTML strings), so no values can inject markup.
export function buildCheckpointPopup(cp: Checkpoint, lastIndex: number): HTMLElement {
  const title =
    cp.index === 0 ? 'Origin' : cp.index === lastIndex ? 'Destination' : `Checkpoint ${cp.index}`
  const root = el('div', 'min-w-[230px] space-y-2 text-xs')

  const header = el('div', 'flex items-baseline justify-between gap-4')
  header.append(
    el('span', 'text-sm font-semibold text-white', title),
    el('span', 'text-slate-400', `${cp.distance_mi.toFixed(1)} mi`),
  )
  root.append(
    header,
    el('div', 'text-slate-300', `ETA ${formatDateTime(cp.eta)}`),
    badge(cp.risk.label, RISK_META[cp.risk.level].color),
  )

  const w = cp.weather
  if (w.status === 'ok') {
    root.append(
      grid([
        ['Wind gusts', reading(w.gust_mph, 'mph')],
        ['Sustained wind', reading(w.wind_mph, 'mph')],
        ['Rain', reading(w.rain_in_hr, 'in/hr')],
        ['Snow', reading(w.snow_in_hr, 'in/hr')],
      ]),
    )
  } else {
    const reason = w.status === 'out_of_range' ? 'outside the forecast range' : 'data missing'
    root.append(el('div', 'text-amber-300', `Forecast unavailable (${reason})`))
  }

  root.append(el('div', 'border-t border-slate-700 pt-2 text-slate-400', cp.risk.rule))
  return root
}

// A forecast sample is a snapshot at one hour, not the truck's arrival time.
export function buildForecastPopup(point: CorridorPoint, hour: number, referenceIso: string): HTMLElement {
  const level = riskKeyFromValue(point.risk[hour] ?? null)
  const root = el('div', 'min-w-[230px] space-y-2 text-xs')

  const header = el('div', 'flex items-baseline justify-between gap-4')
  header.append(
    el('span', 'text-sm font-semibold text-white', 'Forecast sample'),
    el('span', 'text-slate-400', `mile ${point.distance_mi.toFixed(0)}`),
  )
  root.append(
    header,
    el('div', 'text-slate-300', formatForecastTime(referenceIso, hour)),
    el('div', 'text-slate-500', `${point.lat.toFixed(2)}°, ${point.lon.toFixed(2)}°`),
    badge(RISK_META[level].label, RISK_META[level].color),
    grid([
      ['Wind gusts', reading(point.gust_mph[hour] ?? null, 'mph')],
      ['Rain', reading(point.rain_in_hr[hour] ?? null, 'in/hr')],
      ['Snow', reading(point.snow_in_hr[hour] ?? null, 'in/hr')],
    ]),
  )
  if (level === 'unknown') {
    root.append(el('div', 'text-amber-300', 'No forecast available for this hour.'))
  }
  return root
}