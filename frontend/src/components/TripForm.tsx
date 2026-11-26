import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import type { AnalyzeRequest, Interval } from '../types/route'

const INTERVALS: Interval[] = [10, 25, 50]
const TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone

const inputClass =
  'w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 ' +
  'placeholder-slate-500 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 ' +
  'disabled:opacity-60 [color-scheme:dark]'

function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function defaultDeparture(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000)
  d.setMinutes(0, 0, 0)
  return toLocalInputValue(d)
}

interface FieldProps {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}

function Field({ id, label, error, hint, children }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1.5 text-xs text-rose-400" role="alert">{error}</p>
      ) : hint ? (
        <p className="mt-1.5 text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  )
}

interface Props {
  loading: boolean
  fieldErrors: Record<string, string[]>
  onSubmit: (request: AnalyzeRequest) => void
}

export default function TripForm({ loading, fieldErrors, onSubmit }: Props) {
  const [origin, setOrigin] = useState('Chicago, IL')
  const [destination, setDestination] = useState('Milwaukee, WI')
  const [departure, setDeparture] = useState(defaultDeparture)
  const [weight, setWeight] = useState('35000')
  const [intervalMiles, setIntervalMiles] = useState<Interval>(25)
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({})

  const errorFor = (key: string) => localErrors[key] ?? fieldErrors[key]?.[0]

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const when = new Date(departure)
    const load = Number(weight)
    const errors: Record<string, string> = {}
    if (!origin.trim()) errors.origin = 'Enter a starting location.'
    if (!destination.trim()) errors.destination = 'Enter a destination.'
    if (Number.isNaN(when.getTime())) errors.departure_time = 'Choose a departure date and time.'
    if (weight.trim() === '' || !Number.isFinite(load) || load < 0 || load > 200_000) {
      errors.load_weight = 'Enter a weight between 0 and 200,000 lb.'
    }
    setLocalErrors(errors)
    if (Object.keys(errors).length > 0) return

    onSubmit({
      origin: origin.trim(),
      destination: destination.trim(),
      departure_time: when.toISOString(),
      load_weight: load,
      interval_miles: intervalMiles,
    })
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5 rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="text-sm font-semibold text-white">Plan a trip</h2>

      <Field id="origin" label="Origin" error={errorFor('origin')}>
        <input id="origin" className={inputClass} value={origin} disabled={loading}
          placeholder="e.g. Chicago, IL" onChange={(e) => setOrigin(e.target.value)} />
      </Field>

      <Field id="destination" label="Destination" error={errorFor('destination')}>
        <input id="destination" className={inputClass} value={destination} disabled={loading}
          placeholder="e.g. Milwaukee, WI" onChange={(e) => setDestination(e.target.value)} />
      </Field>

      <Field id="departure" label="Departure" error={errorFor('departure_time')}
        hint={`Your local time (${TIME_ZONE}). Forecast covers about 15 days.`}>
        <input id="departure" type="datetime-local" className={inputClass} value={departure}
          disabled={loading} onChange={(e) => setDeparture(e.target.value)} />
      </Field>

      <Field id="weight" label="Load weight (lb)" error={errorFor('load_weight')}
        hint="Heavy loads trigger stricter wind rules above 30,000 and 40,000 lb.">
        <input id="weight" type="number" inputMode="numeric" min={0} max={200000} step={500}
          className={inputClass} value={weight} disabled={loading}
          onChange={(e) => setWeight(e.target.value)} />
      </Field>

      <Field id="interval" label="Checkpoint interval" error={errorFor('interval_miles')}
        hint={`Weather is sampled every ${intervalMiles} miles along each route.`}>
        <div role="radiogroup" aria-label="Checkpoint interval" className="grid grid-cols-3 gap-2">
          {INTERVALS.map((value) => (
            <button key={value} type="button" role="radio" aria-checked={intervalMiles === value}
              disabled={loading} onClick={() => setIntervalMiles(value)}
              className={
                'rounded-lg border px-3 py-2 text-sm font-medium transition disabled:opacity-60 ' +
                (intervalMiles === value
                  ? 'border-sky-500 bg-sky-500/15 text-sky-300'
                  : 'border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-500')
              }>
              {value} mi
            </button>
          ))}
        </div>
      </Field>

      <button type="submit" disabled={loading}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-sky-500 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-70">
        {loading && (
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
            <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
          </svg>
        )}
        {loading ? 'Analyzing…' : 'Analyze routes'}
      </button>
    </form>
  )
}