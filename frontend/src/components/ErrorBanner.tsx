import type { ApiError } from '../api/client'

const TITLES: Record<string, string> = {
  invalid_input: 'Please check your inputs',
  location_not_found: 'Location not found',
  no_route: 'No route found',
  routing_unavailable: 'Routing service unavailable',
  weather_unavailable: 'Weather service unavailable',
  network_error: 'Connection problem',
}

export default function ErrorBanner({ error }: { error: ApiError }) {
  const message =
    error.code === 'invalid_input' ? 'Some fields need attention. See the highlighted fields.' : error.message
  return (
    <div role="alert" className="rounded-2xl border border-rose-500/40 bg-rose-500/5 p-5">
      <h2 className="text-base font-semibold text-rose-300">{TITLES[error.code] ?? 'Something went wrong'}</h2>
      <p className="mt-1 text-sm text-slate-300">{message}</p>
    </div>
  )
}