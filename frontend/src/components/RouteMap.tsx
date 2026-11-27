import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import mapboxgl from 'mapbox-gl'
import type { GeoJSONSource, Map as MapboxMap, Popup as MapboxPopup } from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import { buildCheckpointPopup, buildForecastPopup } from '../lib/popup'
import { RISK_META, RISK_ORDER } from '../lib/risk'
import type { CorridorResponse, MapMode, Route } from '../types/route'
import MapLegend from './MapLegend'

// Mapbox style expressions are loosely typed to keep this file readable.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Expr = any

const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN as string | undefined
const MAP_STYLE = 'mapbox://styles/mapbox/dark-v11'
const SEGMENTS = 'route-segments'
const CHECKPOINTS = 'checkpoints'
const FORECAST = 'forecast'

// Route-risk view shows these; the forecast view shows the others.
const ROUTE_ONLY_LAYERS = ['route-casing', 'routes-selected', 'checkpoint-circles']
const FORECAST_ONLY_LAYERS = ['forecast-circles', 'route-plain']
const SELECTED_LAYERS = ['route-casing', 'routes-selected', 'route-plain']
const CLICK_GUARD_LAYERS = ['checkpoint-circles', 'routes-selected', 'forecast-circles', 'route-plain']

const RISK_COLOR: Expr = [
  'match',
  ['get', 'level'],
  ...RISK_ORDER.flatMap((key) => [key, RISK_META[key].color]),
  RISK_META.unknown.color,
]
const CHECKPOINT_RADIUS: Expr = ['case', ['==', ['get', 'endpoint'], 1], 8, 5.5]
// About 15 miles on the ground at any zoom, with a minimum size when zoomed far out.
const FORECAST_RADIUS: Expr = ['interpolate', ['exponential', 2], ['zoom'], 3, 5, 6, 13, 11, 410]

// Color of each forecast sample for one hour: reads that hour's property (r0 .. r48).
// A null value (unknown) matches nothing and falls through to the gray default.
const forecastColor = (hour: number): Expr => [
  'match',
  ['get', `r${hour}`],
  0, RISK_META.low.color,
  1, RISK_META.moderate.color,
  2, RISK_META.high.color,
  3, RISK_META.severe.color,
  4, RISK_META.no_travel.color,
  RISK_META.unknown.color,
]

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }

const mutedFilter = (id: string | null): Expr => ['!=', ['get', 'routeId'], id ?? '']
const selectedFilter = (id: string | null): Expr => ['==', ['get', 'routeId'], id ?? '']

// Every route, split into risk-colored stretches. Built once per analysis result.
function buildSegments(routes: Route[]): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = []
  for (const route of routes) {
    for (const seg of route.segments) {
      const coordinates = route.geometry.coordinates.slice(seg.start_index, seg.end_index + 1)
      if (coordinates.length < 2) continue
      features.push({
        type: 'Feature',
        properties: { routeId: route.id, level: seg.level },
        geometry: { type: 'LineString', coordinates },
      })
    }
  }
  return { type: 'FeatureCollection', features }
}

function buildCheckpoints(route: Route | undefined): FeatureCollection<Point> {
  if (!route) return { type: 'FeatureCollection', features: [] }
  const last = route.checkpoints.length - 1
  return {
    type: 'FeatureCollection',
    features: route.checkpoints.map((cp, i) => ({
      type: 'Feature',
      properties: { index: i, level: cp.risk.level, endpoint: i === 0 || i === last ? 1 : 0 },
      geometry: { type: 'Point', coordinates: [cp.lon, cp.lat] },
    })),
  }
}

// One feature per sample point with a risk value for every hour (r0 .. r48), so the
// slider only changes which property the paint expression reads. No data is re-sent.
function buildForecast(corridor: CorridorResponse | null): FeatureCollection<Point> {
  if (!corridor) return { type: 'FeatureCollection', features: [] }
  return {
    type: 'FeatureCollection',
    features: corridor.points.map((p, i) => {
      const properties: Record<string, number | null> = { i }
      p.risk.forEach((value, hour) => {
        properties[`r${hour}`] = value
      })
      return {
        type: 'Feature',
        properties,
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      }
    }),
  }
}

function fitToRoutes(map: MapboxMap, routes: Route[]) {
  if (routes.length === 0) return
  const bounds = new mapboxgl.LngLatBounds()
  for (const route of routes) {
    for (const coordinate of route.geometry.coordinates) bounds.extend(coordinate)
  }
  map.fitBounds(bounds, { padding: 60, duration: 800, maxZoom: 11 })
}

function createMap(container: HTMLDivElement, token: string): MapboxMap | null {
  try {
    mapboxgl.accessToken = token
    return new mapboxgl.Map({ container, style: MAP_STYLE, center: [-96, 38.5], zoom: 3.2 })
  } catch {
    return null // e.g. WebGL unavailable
  }
}

function setupLayers(map: MapboxMap) {
  map.addSource(SEGMENTS, { type: 'geojson', data: EMPTY })
  map.addSource(CHECKPOINTS, { type: 'geojson', data: EMPTY })
  map.addSource(FORECAST, { type: 'geojson', data: EMPTY })

  // Other routes: muted gray (both views).
  map.addLayer({
    id: 'routes-muted',
    type: 'line',
    source: SEGMENTS,
    filter: mutedFilter(null),
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#94a3b8', 'line-width': 4, 'line-opacity': 0.5 },
  })
  // Route-risk view: dark casing underneath for contrast, then risk colors on top.
  map.addLayer({
    id: 'route-casing',
    type: 'line',
    source: SEGMENTS,
    filter: selectedFilter(null),
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#020617', 'line-width': 10, 'line-opacity': 0.8 },
  })
  map.addLayer({
    id: 'routes-selected',
    type: 'line',
    source: SEGMENTS,
    filter: selectedFilter(null),
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': RISK_COLOR, 'line-width': 6 },
  })
  // Forecast view: soft risk-colored areas along the corridor, with a plain route line on top.
  map.addLayer({
    id: 'forecast-circles',
    type: 'circle',
    source: FORECAST,
    layout: { visibility: 'none' },
    paint: {
      'circle-radius': FORECAST_RADIUS,
      'circle-color': forecastColor(0),
      'circle-opacity': 0.55,
      'circle-blur': 0.6,
    },
  })
  map.addLayer({
    id: 'route-plain',
    type: 'line',
    source: SEGMENTS,
    filter: selectedFilter(null),
    layout: { 'line-cap': 'round', 'line-join': 'round', visibility: 'none' },
    paint: { 'line-color': '#e2e8f0', 'line-width': 3, 'line-opacity': 0.9 },
  })
  map.addLayer({
    id: 'checkpoint-circles',
    type: 'circle',
    source: CHECKPOINTS,
    paint: {
      'circle-radius': CHECKPOINT_RADIUS,
      'circle-color': RISK_COLOR,
      'circle-stroke-color': '#f8fafc',
      'circle-stroke-width': 2,
    },
  })
}

function MapMessage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid h-full place-items-center bg-slate-900/90 p-6 text-center">
      <div>
        <p className="text-sm font-semibold text-slate-200">{title}</p>
        <p className="mx-auto mt-1 max-w-sm text-xs text-slate-400">{children}</p>
      </div>
    </div>
  )
}

interface Props {
  routes: Route[]
  selectedId: string | null
  onSelect: (id: string) => void
  mode: MapMode
  corridor: CorridorResponse | null
  hour: number
}

export default function RouteMap({ routes, selectedId, onSelect, mode, corridor, hour }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapboxMap | null>(null)
  const popupRef = useRef<MapboxPopup | null>(null)
  const popupIndexRef = useRef<number | null>(null) // forecast sample shown in the open popup
  // Map event handlers are registered once, so they read the latest props through refs.
  const routesRef = useRef(routes)
  const selectedRef = useRef(selectedId)
  const onSelectRef = useRef(onSelect)
  const corridorRef = useRef(corridor)
  const hourRef = useRef(hour)
  const [ready, setReady] = useState(false)
  const [mapError, setMapError] = useState<string | null>(null)

  useEffect(() => {
    routesRef.current = routes
    selectedRef.current = selectedId
    onSelectRef.current = onSelect
    corridorRef.current = corridor
    hourRef.current = hour
  })

  // Create the map once; remove it on unmount (also correct under StrictMode's double run).
  useEffect(() => {
    const container = containerRef.current
    if (!TOKEN || !container) return
    const map = createMap(container, TOKEN)
    if (!map) {
      queueMicrotask(() => setMapError('This browser could not start the map (WebGL may be unavailable).'))
      return
    }
    mapRef.current = map
    let loaded = false

    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
    // Only a failure before the style loads is fatal; later tile hiccups are ignored.
    map.on('error', () => {
      if (!loaded) setMapError('The map could not load. Check VITE_MAPBOX_TOKEN and your connection.')
    })

    map.on('load', () => {
      loaded = true
      setupLayers(map)

      const pointer = () => {
        map.getCanvas().style.cursor = 'pointer'
      }
      const reset = () => {
        map.getCanvas().style.cursor = ''
      }
      for (const layer of ['routes-muted', 'checkpoint-circles', 'forecast-circles']) {
        map.on('mouseenter', layer, pointer)
        map.on('mouseleave', layer, reset)
      }

      // Clicking a muted route selects it, unless the click was really on a checkpoint,
      // the selected route or a forecast area (they overlap at shared origins and roads).
      map.on('click', 'routes-muted', (e) => {
        const covered = map.queryRenderedFeatures(e.point, { layers: CLICK_GUARD_LAYERS })
        if (covered.length > 0) return
        const routeId = e.features?.[0]?.properties?.routeId
        if (typeof routeId === 'string') onSelectRef.current(routeId)
      })

      map.on('click', 'checkpoint-circles', (e) => {
        const index = e.features?.[0]?.properties?.index
        const route = routesRef.current.find((r) => r.id === selectedRef.current)
        const checkpoint = typeof index === 'number' ? route?.checkpoints[index] : undefined
        if (!route || !checkpoint) return
        popupRef.current?.remove()
        popupIndexRef.current = null
        popupRef.current = new mapboxgl.Popup({ className: 'wr-popup', maxWidth: '300px', offset: 12 })
          .setLngLat([checkpoint.lon, checkpoint.lat])
          .setDOMContent(buildCheckpointPopup(checkpoint, route.checkpoints.length - 1))
          .addTo(map)
      })

      map.on('click', 'forecast-circles', (e) => {
        const index = e.features?.[0]?.properties?.i
        const data = corridorRef.current
        const point = typeof index === 'number' ? data?.points[index] : undefined
        if (!data || !point) return
        popupRef.current?.remove()
        popupIndexRef.current = index as number
        popupRef.current = new mapboxgl.Popup({ className: 'wr-popup', maxWidth: '300px', offset: 12 })
          .setLngLat([point.lon, point.lat])
          .setDOMContent(buildForecastPopup(point, hourRef.current, data.reference_time))
          .addTo(map)
      })

      setReady(true)
    })

    return () => {
      popupRef.current?.remove()
      popupRef.current = null
      map.remove()
      mapRef.current = null
      setReady(false)
    }
  }, [])

  // New analysis result: replace route data and fit the view.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    ;(map.getSource(SEGMENTS) as GeoJSONSource | undefined)?.setData(buildSegments(routes))
    fitToRoutes(map, routes)
  }, [ready, routes])

  // Selection changed: swap layer filters and checkpoint data (no geometry rebuild).
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    map.setFilter('routes-muted', mutedFilter(selectedId))
    for (const id of SELECTED_LAYERS) map.setFilter(id, selectedFilter(selectedId))
    ;(map.getSource(CHECKPOINTS) as GeoJSONSource | undefined)?.setData(
      buildCheckpoints(routes.find((r) => r.id === selectedId)),
    )
    popupRef.current?.remove()
  }, [ready, routes, selectedId])

  // View mode changed: show only that view's layers.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    const routeView = mode === 'route'
    for (const id of ROUTE_ONLY_LAYERS) map.setLayoutProperty(id, 'visibility', routeView ? 'visible' : 'none')
    for (const id of FORECAST_ONLY_LAYERS) map.setLayoutProperty(id, 'visibility', routeView ? 'none' : 'visible')
    popupRef.current?.remove()
  }, [ready, mode])

  // Forecast data for the selected route arrived (or was cleared): replace the sample points.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    ;(map.getSource(FORECAST) as GeoJSONSource | undefined)?.setData(buildForecast(corridor))
  }, [ready, corridor])

  // Slider moved: only the paint expression changes. No request and no data re-upload.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    map.setPaintProperty('forecast-circles', 'circle-color', forecastColor(hour))
  }, [ready, hour])

  // Keep an open forecast popup in step with the slider.
  useEffect(() => {
    const popup = popupRef.current
    const index = popupIndexRef.current
    if (!corridor || !popup || index === null || !popup.isOpen()) return
    const point = corridor.points[index]
    if (point) popup.setDOMContent(buildForecastPopup(point, hour, corridor.reference_time))
  }, [corridor, hour])

  if (!TOKEN) {
    return (
      <div className="h-[540px] overflow-hidden rounded-2xl border border-slate-800">
        <MapMessage title="Map unavailable">
          Add <code>VITE_MAPBOX_TOKEN=pk...</code> to <code>frontend/.env.local</code> and restart{' '}
          <code>npm run dev</code>.
        </MapMessage>
      </div>
    )
  }

  return (
    <div className="relative h-[540px] overflow-hidden rounded-2xl border border-slate-800 bg-slate-900">
      <div ref={containerRef} className="h-full w-full" />
      {!ready && !mapError && (
        <div className="absolute inset-0 z-20 grid place-items-center bg-slate-900/80 text-sm text-slate-400">
          Loading map…
        </div>
      )}
      {mapError && (
        <div className="absolute inset-0 z-20">
          <MapMessage title="Map unavailable">{mapError}</MapMessage>
        </div>
      )}
      {ready && <MapLegend mode={mode} />}
    </div>
  )
}