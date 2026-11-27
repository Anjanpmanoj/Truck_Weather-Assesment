import { useEffect, useState } from 'react'
import { ApiError, fetchCorridor } from '../api/client'
import type { AnalyzeResponse, CorridorResponse } from '../types/route'

interface Cache {
  trip: AnalyzeResponse
  byRoute: Record<string, CorridorResponse>
}
interface Failure {
  trip: AnalyzeResponse
  routeId: string
  message: string
}

export interface CorridorState {
  data: CorridorResponse | null
  loading: boolean
  error: string | null
  retry: () => void
}

// Fetches a route's forecast corridor once, the first time it is needed, and caches it
// until the next analysis. Moving the hour slider never touches this hook.
export function useCorridor(trip: AnalyzeResponse, routeId: string | null, enabled: boolean): CorridorState {
  const [cache, setCache] = useState<Cache>({ trip, byRoute: {} })
  const [failure, setFailure] = useState<Failure | null>(null)

  const data = routeId && cache.trip === trip ? (cache.byRoute[routeId] ?? null) : null
  const error =
    failure && failure.trip === trip && failure.routeId === routeId ? failure.message : null

  useEffect(() => {
    if (!enabled || !routeId || data || error) return
    const route = trip.routes.find((r) => r.id === routeId)
    if (!route) return

    const controller = new AbortController()
    fetchCorridor(
      {
        load_weight: trip.request.load_weight,
        points: route.checkpoints.map(({ lat, lon, distance_mi }) => ({ lat, lon, distance_mi })),
      },
      controller.signal,
    )
      .then((result) =>
        setCache((prev) => ({
          trip,
          byRoute: { ...(prev.trip === trip ? prev.byRoute : {}), [routeId]: result },
        })),
      )
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setFailure({
          trip,
          routeId,
          message: e instanceof ApiError ? e.message : 'Could not load the forecast.',
        })
      })
    return () => controller.abort()
  }, [enabled, routeId, trip, data, error])

  return {
    data,
    loading: enabled && !!routeId && !data && !error,
    error,
    retry: () => setFailure(null),
  }
}