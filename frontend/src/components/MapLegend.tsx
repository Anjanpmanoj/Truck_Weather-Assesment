import { RISK_META, RISK_ORDER } from '../lib/risk'

// Top-left, so it does not cover the Mapbox logo (bottom-left) or zoom controls (top-right).
export default function MapLegend() {
  return (
    <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-lg border border-slate-700 bg-slate-900/90 px-3 py-2 text-xs text-slate-300 backdrop-blur">
      <p className="mb-1.5 font-semibold text-slate-200">Risk along selected route</p>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1">
        {RISK_ORDER.map((key) => (
          <li key={key} className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded-full" style={{ backgroundColor: RISK_META[key].color }} />
            {RISK_META[key].label}
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-slate-500">Click a dot for details. Click a gray route to select it.</p>
    </div>
  )
}