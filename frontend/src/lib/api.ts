/**
 * API client.
 *
 * One place that knows about the backend URL, the auth header and the
 * backend's error envelope. Components never call fetch directly.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1"
const TOKEN_KEY = "apa.token"

export class ApiError extends Error {
  status: number
  code: string
  details: unknown

  constructor(message: string, status: number, code = "error", details: unknown = null) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.details = details
  }
}

export const tokenStore = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* storage unavailable (private mode) - session stays in memory only */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* nothing to do */
    }
  },
}

type RequestOptions = {
  method?: string
  body?: unknown
  formData?: FormData
  signal?: AbortSignal
  auth?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, formData, signal, auth = true } = options
  const headers: Record<string, string> = {}

  if (auth) {
    const token = tokenStore.get()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  if (body !== undefined) headers["Content-Type"] = "application/json"

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
    signal,
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: any = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!response.ok) {
    // The backend wraps domain errors as { error: { code, message, details } }.
    const envelope = payload?.error
    const message =
      envelope?.message ??
      payload?.detail ??
      (typeof payload === "string" ? payload : null) ??
      `Request failed with status ${response.status}`
    throw new ApiError(
      typeof message === "string" ? message : JSON.stringify(message),
      response.status,
      envelope?.code ?? "http_error",
      envelope?.details ?? payload,
    )
  }

  return payload as T
}

export const api = {
  get: <T,>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  put: <T,>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
  postForm: <T,>(path: string, formData: FormData) => request<T>(path, { method: "POST", formData }),
  /** Public endpoints that must not send a stale token. */
  postPublic: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body, auth: false }),
}

/** Absolute URL for links the browser follows directly (file downloads). */
export function fileUrl(quotationId: string): string {
  return `${BASE_URL}/quotations/${quotationId}/file`
}
