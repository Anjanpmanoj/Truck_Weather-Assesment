import type { Recommendation, Route } from '../types/route'

interface Props {
  recommendation: Recommendation
  notes: string[]
  routes: Route[]
}

export default function RecommendationBanner({ recommendation, notes, routes }: Props) {
  const { safe, explanation, warnings } = recommendation
  const label = routes.find((r) => r.id === recommendation.route_id)?.label ?? recommendation.route_id

  return (
    <section aria-live="polite"
      className={
        'rounded-2xl border p-5 ' +
        (safe ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-rose-500/40 bg-rose-500/5')
      }>
      <p className={'text-xs font-semibold uppercase tracking-wider ' + (safe ? 'text-emerald-400' : 'text-rose-400')}>
        {safe ? 'Recommendation' : 'Warning'}
      </p>
      <h2 className="mt-1 text-xl font-semibold text-white">
        {safe ? `Take ${label}` : 'No safe route at this departure time'}
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-slate-300">{explanation}</p>

      {warnings.length > 0 && (
        <ul className="mt-3 space-y-1">
          {warnings.map((w) => (
            <li key={w} className="text-sm text-amber-300">⚠ {w}</li>
          ))}
        </ul>
      )}
      {notes.length > 0 && (
        <ul className="mt-3 space-y-1">
          {notes.map((n) => (
            <li key={n} className="text-xs text-slate-400">ℹ {n}</li>
          ))}
        </ul>
      )}
    </section>
  )
}