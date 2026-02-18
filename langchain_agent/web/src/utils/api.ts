/**
 * API utility with same-origin authentication.
 *
 * Uses origin-based authentication: only requests from the UI
 * (same domain) are accepted. No API key needed.
 */

// When frontend and API are on the same domain (Cloud Run, localhost),
// use relative URLs (empty string) - browser will use the current origin automatically.
// The browser automatically sends the Origin header, which the backend validates.
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/**
 * Create headers for API requests.
 *
 * Note: No API key is needed. The browser automatically sends the Origin header,
 * which the server validates to ensure requests come from the UI.
 */
function createHeaders(additionalHeaders?: Record<string, string>): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    ...additionalHeaders,
  }
}

/**
 * Make an authenticated API request.
 *
 * @param endpoint - API endpoint (e.g., '/api/conversations')
 * @param options - Fetch options (method, body, etc.)
 * @returns Fetch response
 */
export async function apiFetch(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const url = `${API_BASE_URL}${endpoint}`

  const headers = createHeaders(
    options.headers as Record<string, string> | undefined
  )

  return fetch(url, {
    ...options,
    headers,
  })
}

/**
 * GET request with authentication.
 */
export async function apiGet(endpoint: string): Promise<Response> {
  return apiFetch(endpoint, { method: 'GET' })
}

/**
 * POST request with authentication.
 */
export async function apiPost(endpoint: string, body?: unknown): Promise<Response> {
  return apiFetch(endpoint, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}

/**
 * DELETE request with authentication.
 */
export async function apiDelete(endpoint: string): Promise<Response> {
  return apiFetch(endpoint, { method: 'DELETE' })
}
