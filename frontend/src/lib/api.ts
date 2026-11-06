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

/** The server (or the proxy in front of it) is restarting or busy: a short wait usually fixes it. */
const TRANSIENT = new Set([502, 503, 504])
const RETRY_DELAYS_MS = [500, 1500, 3500]
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const FRIENDLY: Record<number, string> = {
  502: "The service is starting up or busy. Please wait a few seconds and try again.",
  503: "The service is busy right now. Please try again in a minute.",
  504: "The service took too long to answer. Please try again.",
  500: "Something went wrong on our side. Please try again.",
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, formData, signal, auth = true } = options
  // Reading is safe to repeat, so a brief outage is retried quietly. Writes are never repeated.
  const attempts = method === "GET" ? RETRY_DELAYS_MS.length + 1 : 1
  for (let attempt = 1; ; attempt++) {
    try {
      return await send<T>(path, { method, body, formData, signal, auth })
    } catch (error) {
      const transient = (error instanceof ApiError && TRANSIENT.has(error.status)) || error instanceof NetworkError
      if (!transient || attempt >= attempts || signal?.aborted) throw error
      await sleep(RETRY_DELAYS_MS[attempt - 1])
    }
  }
}

class NetworkError extends ApiError {
  constructor() {
    super("We could not reach the server. Check your internet connection and try again.", 0, "network_error")
  }
}

async function send<T>(path: string, options: RequestOptions): Promise<T> {
  const { method = "GET", body, formData, signal, auth = true } = options
  const headers: Record<string, string> = {}

  if (auth) {
    const token = tokenStore.get()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  if (body !== undefined) headers["Content-Type"] = "application/json"

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new NetworkError()
  }

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
    // Gateway and server failures carry no useful message: say something a person can act on.
    const message =
      envelope?.message ??
      FRIENDLY[response.status] ??
      (typeof payload?.detail === "string" ? payload.detail : null) ??
      `Something went wrong (error ${response.status}). Please try again.`
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

/**
 * Download (or open) a protected file. A plain <a href> can't send the bearer
 * token, so the file is fetched with it and handed to the browser as a blob.
 */
export async function downloadFile(path: string, filename?: string): Promise<void> {
  const token = tokenStore.get()
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new ApiError(`Download failed (${response.status})`, response.status)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement("a")
  link.href = url
  if (filename) link.download = filename
  else Object.assign(link, { target: "_blank", rel: "noreferrer" })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export const fileUrl = (quotationId: string) => `/quotations/${quotationId}/file`
