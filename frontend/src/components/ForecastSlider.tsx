import { formatForecastTime } from '../lib/format'

interface Props {
  referenceTime: string | null
  hour: number
  maxHour: number
  disabled: boolean
  onChange: (hour: number) => void
}

const TICKS = [0, 12, 24, 36, 48]

export default function ForecastSlider({ referenceTime, hour, maxHour, disabled, onChange }: Props) {
  const when = referenceTime ? formatForecastTime(referenceTime, hour) : 'Forecast time'
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-white">{when}</p>
        <p className="text-xs text-slate-400">{hour === 0 ? 'Now (current hour)' : `+${hour} h from now`}</p>
      </div>
      <input
        type="range"
        min={0}
        max={maxHour}
        step={1}
        value={hour}
        disabled={disabled}
        aria-label="Forecast hour"
        aria-valuetext={when}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-3 w-full accent-sky-500 disabled:opacity-50"
      />
      <div className="relative mx-2 mt-1 h-4 text-xs text-slate-500">
        {TICKS.filter((t) => t <= maxHour).map((t) => (
          <span key={t} className="absolute -translate-x-1/2" style={{ left: `${(t / maxHour) * 100}%` }}>
            {t === 0 ? 'Now' : `+${t}h`}
          </span>
        ))}
      </div>
    </div>
  )
}