import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import mapboxgl from 'mapbox-gl'
import type { GeoJSONSource, Map as MapboxMap, Popup as MapboxPopup } from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import { buildCheckpointPopup } from '../lib/popup'
import { RISK_META, RISK_ORDER } from '../lib/risk'
import type { Route } from '../types/route'
import MapLegend from './MapLegend'

// Mapbox style expressions are loosely typed to keep this file readable.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Expr = any

const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN as string | undefined
const MAP_STYLE = 'mapbox://styles/mapbox/dark-v11'
const SEGMENTS = 'route-segments'
const CHECKPOINTS = 'checkpoints'

const RISK_COLOR: Expr = [
  'match',
  ['get', 'level'],
  ...RISK_ORDER.flatMap((key) => [key, RISK_META[key].color]),
  RISK_META.unknown.color,
]
const CHECKPOINT_RADIUS: Expr = ['case', ['==', ['get', 'endpoint'], 1], 8, 5.5]

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

  // Other routes: muted gray.
  map.addLayer({
    id: 'routes-muted',
    type: 'line',
    source: SEGMENTS,
    filter: mutedFilter(null),
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#94a3b8', 'line-width': 4, 'line-opacity': 0.5 },
  })
  // Selected route: dark casing underneath for contrast, then risk colors on top.
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
}

export default function RouteMap({ routes, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapboxMap | null>(null)
  const popupRef = useRef<MapboxPopup | null>(null)
  // Map event handlers are registered once, so they read the latest props through refs.
  const routesRef = useRef(routes)
  const selectedRef = useRef(selectedId)
  const onSelectRef = useRef(onSelect)
  const [ready, setReady] = useState(false)
  const [mapError, setMapError] = useState<string | null>(null)

  useEffect(() => {
    routesRef.current = routes
    selectedRef.current = selectedId
    onSelectRef.current = onSelect
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
      for (const layer of ['routes-muted', 'checkpoint-circles']) {
        map.on('mouseenter', layer, pointer)
        map.on('mouseleave', layer, reset)
      }

      // Clicking a muted route selects it, unless the click was really on a checkpoint
      // or on the selected route (they overlap at shared origins and roads).
      map.on('click', 'routes-muted', (e) => {
        const covered = map.queryRenderedFeatures(e.point, {
          layers: ['checkpoint-circles', 'routes-selected'],
        })
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
        popupRef.current = new mapboxgl.Popup({ className: 'wr-popup', maxWidth: '300px', offset: 12 })
          .setLngLat([checkpoint.lon, checkpoint.lat])
          .setDOMContent(buildCheckpointPopup(checkpoint, route.checkpoints.length - 1))
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
    map.setFilter('route-casing', selectedFilter(selectedId))
    map.setFilter('routes-selected', selectedFilter(selectedId))
    ;(map.getSource(CHECKPOINTS) as GeoJSONSource | undefined)?.setData(
      buildCheckpoints(routes.find((r) => r.id === selectedId)),
    )
    popupRef.current?.remove()
  }, [ready, routes, selectedId])

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
      {ready && <MapLegend />}
    </div>
  )
}