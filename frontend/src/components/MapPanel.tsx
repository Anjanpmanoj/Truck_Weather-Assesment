import { useState } from 'react'
import { useCorridor } from '../hooks/useCorridor'
import type { AnalyzeResponse, MapMode } from '../types/route'
import ForecastSlider from './ForecastSlider'
import RouteMap from './RouteMap'

interface Props {
  data: AnalyzeResponse
  selectedId: string | null
  onSelect: (id: string) => void
}

const MODES: { value: MapMode; label: string }[] = [
  { value: 'route', label: 'Route risk' },
  { value: 'forecast', label: '48-hour forecast' },
]

export default function MapPanel({ data, selectedId, onSelect }: Props) {
  const [mode, setMode] = useState<MapMode>('route')
  const [hour, setHour] = useState(0)
  const corridor = useCorridor(data, selectedId, mode === 'forecast')

  const selectedLabel = data.routes.find((r) => r.id === selectedId)?.label ?? 'the selected route'
  const noForecast =
    corridor.data !== null && corridor.data.points.every((p) => p.risk.every((r) => r === null))

  return (
    <section className="space-y-3" aria-label="Map">
      <div className="flex flex-wrap items-center gap-3">
        <div role="radiogroup" aria-label="Map view" className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-1">
          {MODES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={mode === value}
              onClick={() => setMode(value)}
              className={
                'rounded-md px-3 py-1.5 text-sm font-medium transition ' +
                (mode === value ? 'bg-sky-500/20 text-sky-300' : 'text-slate-400 hover:text-slate-200')
              }
            >
              {label}
            </button>
          ))}
        </div>
        <p className="min-w-0 flex-1 text-xs text-slate-400">
          {mode === 'route'
            ? "Weather at the time the truck reaches each checkpoint (its ETA). This is what the recommendation is based on."
            : 'A forecast snapshot of weather across the corridor at the hour you pick, counted from now. It does not depend on your departure time and does not change the recommendation.'}
        </p>
      </div>

      {mode === 'forecast' && (
        <div className="space-y-2">
          <ForecastSlider
            referenceTime={corridor.data?.reference_time ?? null}
            hour={hour}
            maxHour={corridor.data?.hours ?? 48}
            disabled={!corridor.data}
            onChange={setHour}
          />
          {corridor.loading && (
            <p className="flex items-center gap-2 text-sm text-slate-400" role="status">
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
                <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
              </svg>
              Loading the 48-hour forecast for {selectedLabel}…
            </p>
          )}
          {corridor.error && (
            <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-rose-500/40 bg-rose-500/5 px-4 py-3 text-sm text-slate-300">
              <span className="flex-1">{corridor.error}</span>
              <button type="button" onClick={corridor.retry} className="rounded-lg border border-slate-600 px-3 py-1 text-xs font-medium text-slate-200 hover:border-slate-400">
                Retry
              </button>
            </div>
          )}
          {noForecast && (
            <p className="text-sm text-amber-300">No forecast data is available for this corridor right now.</p>
          )}
          {corridor.data?.warnings.map((w) => (
            <p key={w} className="text-xs text-amber-300">⚠ {w}</p>
          ))}
        </div>
      )}

      <RouteMap
        routes={data.routes}
        selectedId={selectedId}
        onSelect={onSelect}
        mode={mode}
        corridor={corridor.data}
        hour={hour}
      />
    </section>
  )
}