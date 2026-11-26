export type RiskLevelKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'
export type RiskKey = RiskLevelKey | 'unknown'
export type Interval = 10 | 25 | 50
export type WeatherStatus = 'ok' | 'out_of_range' | 'missing'
export type RouteSource = 'mapbox-alternative' | 'waypoint-detour'

export interface Place {
  name: string
  lat: number
  lon: number
}

export interface CheckpointWeather {
  status: WeatherStatus
  wind_mph: number | null
  gust_mph: number | null
  rain_in_hr: number | null
  snow_in_hr: number | null
}

export interface CheckpointRisk {
  level: RiskKey
  value: number | null // 0 (Low) to 4 (No Travel); null when unknown
  label: string
  rule: string
}

export interface Checkpoint {
  index: number
  distance_mi: number
  represented_mi: number
  lat: number
  lon: number
  eta: string // ISO 8601, UTC
  weather: CheckpointWeather
  risk: CheckpointRisk
}

// A stretch of the route line: geometry.coordinates.slice(start_index, end_index + 1)
export interface Segment {
  level: RiskKey
  start_index: number
  end_index: number
  start_mi: number
  end_mi: number
}

export interface RouteSummary {
  miles_by_level: Record<RiskKey, number>
  avg_risk: number // 0 to 4, distance-weighted
  has_no_travel: boolean
}

export interface Route {
  id: string
  label: string
  source: RouteSource
  recommended: boolean
  distance_mi: number
  duration_s: number
  arrival_time: string // ISO 8601, UTC
  summary: RouteSummary
  geometry: { type: 'LineString'; coordinates: [number, number][] } // [lon, lat]
  segments: Segment[]
  checkpoints: Checkpoint[]
}

export interface Recommendation {
  route_id: string
  safe: boolean
  explanation: string
  warnings: string[]
}

export interface AnalyzeRequest {
  origin: string
  destination: string
  departure_time: string // ISO 8601 with timezone
  load_weight: number // pounds
  interval_miles: Interval
}

export interface AnalyzeResponse {
  origin: Place | null
  destination: Place | null
  request: { departure_time: string; load_weight: number; interval_miles: Interval }
  recommendation: Recommendation
  notes: string[]
  routes: Route[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, string[]> }
}