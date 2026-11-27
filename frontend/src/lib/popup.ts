import type { Checkpoint } from '../types/route'
import { formatDateTime } from './format'
import { RISK_META } from './risk'

function el(tag: keyof HTMLElementTagNameMap, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function reading(value: number | null, unit: string): string {
  return value === null ? '–' : `${value} ${unit}`
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

  const color = RISK_META[cp.risk.level].color
  const badge = el('span', 'inline-block rounded-full border px-2 py-0.5 font-medium', cp.risk.label)
  badge.style.color = color
  badge.style.borderColor = color
  badge.style.backgroundColor = `${color}1a`

  root.append(header, el('div', 'text-slate-300', `ETA ${formatDateTime(cp.eta)}`), badge)

  const w = cp.weather
  if (w.status === 'ok') {
    const rows: [string, string][] = [
      ['Wind gusts', reading(w.gust_mph, 'mph')],
      ['Sustained wind', reading(w.wind_mph, 'mph')],
      ['Rain', reading(w.rain_in_hr, 'in/hr')],
      ['Snow', reading(w.snow_in_hr, 'in/hr')],
    ]
    const grid = el('dl', 'grid grid-cols-2 gap-x-4 gap-y-1.5')
    for (const [label, value] of rows) {
      const cell = el('div', '')
      cell.append(el('dt', 'text-slate-500', label), el('dd', 'font-medium text-slate-100', value))
      grid.append(cell)
    }
    root.append(grid)
  } else {
    const reason = w.status === 'out_of_range' ? 'outside the forecast range' : 'data missing'
    root.append(el('div', 'text-amber-300', `Forecast unavailable (${reason})`))
  }

  root.append(el('div', 'border-t border-slate-700 pt-2 text-slate-400', cp.risk.rule))
  return root
}