import { useRef, useState } from 'react'
import { ApiError, analyzeTrip } from './api/client'
import ErrorBanner from './components/ErrorBanner'
import LoadingState from './components/LoadingState'
import RecommendationBanner from './components/RecommendationBanner'
import RouteCards from './components/RouteCards'
import MapPanel from './components/MapPanel'
import TripForm from './components/TripForm'
import type { AnalyzeRequest, AnalyzeResponse } from './types/route'

type Status =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; error: ApiError }
  | { kind: 'success' }

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  async function handleAnalyze(request: AnalyzeRequest) {
    abortRef.current?.abort() // cancel a stale request
    const controller = new AbortController()
    abortRef.current = controller
    setStatus({ kind: 'loading' }) // keep the previous result (and the map) mounted
    try {
      const result = await analyzeTrip(request, controller.signal)
      setData(result)
      setSelectedId(result.recommendation.route_id)
      setStatus({ kind: 'success' })
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      const error = e instanceof ApiError ? e : new ApiError('unknown', 'Something went wrong.', 0)
      setData(null) // do not leave results from a different trip on screen
      setStatus({ kind: 'error', error })
    }
  }

  const loading = status.kind === 'loading'
  const fieldErrors =
    status.kind === 'error' && status.error.code === 'invalid_input' ? (status.error.details ?? {}) : {}

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <div className="mx-auto max-w-[1600px]">
          <h1 className="text-lg font-semibold text-white">Weather-Aware Truck Routing</h1>
          <p className="text-sm text-slate-400">
            Compare routes by forecast weather, load weight and travel time.
          </p>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1600px] gap-6 p-6 lg:grid-cols-[360px_1fr]">
        <aside className="self-start lg:sticky lg:top-6">
          <TripForm loading={loading} fieldErrors={fieldErrors} onSubmit={handleAnalyze} />
        </aside>

        <section className="min-w-0 space-y-6">
          {status.kind === 'idle' && (
            <div className="rounded-2xl border border-dashed border-slate-700 p-10 text-center">
              <p className="text-base font-medium text-slate-200">Enter a trip to get started</p>
              <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
                We compare up to three routes, check the weather at the time the truck reaches each
                checkpoint, and recommend the safest one.
              </p>
            </div>
          )}

          {loading && !data && <LoadingState />}
          {loading && data && (
            <p className="text-sm text-slate-400" role="status">
              Updating routes…
            </p>
          )}

          {status.kind === 'error' && <ErrorBanner error={status.error} />}

          {data && (
            <div
              className={'space-y-6 transition-opacity ' + (loading ? 'pointer-events-none opacity-40' : '')}
              aria-busy={loading}
            >
              <RecommendationBanner
                recommendation={data.recommendation}
                notes={data.notes}
                routes={data.routes}
              />
              <MapPanel data={data} selectedId={selectedId} onSelect={setSelectedId} />
              <RouteCards
                routes={data.routes}
                selectedId={selectedId}
                recommendedSafe={data.recommendation.safe}
                onSelect={setSelectedId}
              />
            </div>
          )}
        </section>
      </main>
    </div>
  )
}