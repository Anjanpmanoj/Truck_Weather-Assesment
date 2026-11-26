import type { AnalyzeRequest, AnalyzeResponse, ApiErrorBody } from '../types/route'

export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, string[]>

  constructor(code: string, message: string, status: number, details?: Record<string, string[]>) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

function fallbackMessage(status: number): string {
  return status >= 500
    ? 'The server is not responding. Is the Django backend running on port 8000?'
    : `Request failed (${status}).`
}

export async function analyzeTrip(
  request: AnalyzeRequest,
  signal?: AbortSignal,
): Promise<AnalyzeResponse> {
  let response: Response
  try {
    response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError('network_error', 'Could not reach the server. Check your connection.', 0)
  }

  const data: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const err = (data as Partial<ApiErrorBody> | null)?.error
    throw new ApiError(
      err?.code ?? 'http_error',
      err?.message ?? fallbackMessage(response.status),
      response.status,
      err?.details,
    )
  }
  return data as AnalyzeResponse
}