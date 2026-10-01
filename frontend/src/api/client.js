import axios from 'axios'

// Absolute (http://localhost:8000 in dev) or a same-origin path (/api behind
// the Docker stack's nginx). Both work for REST and for the WebSocket.
const baseURL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export const api = axios.create({ baseURL })

const TOKEN_KEY = 'collabspace.token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

// Attach the bearer token to every request rather than threading it through
// each call site.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let onUnauthorized = null

/** Lets AuthContext react to a token the server has stopped accepting. */
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

/** For non-axios callers (the WebSocket) that learn the token was rejected. */
export function notifyUnauthorized() {
  onUnauthorized?.()
}

/** ws(s):// URL on the API host, carrying the token the server expects. */
export function socketUrl(path) {
  // Join rather than resolve: new URL('/ws/…', 'http://host/api') would drop
  // the /api prefix. Resolving against the page fills in host and scheme
  // when the base is a bare path.
  const url = new URL(`${baseURL}${path}`, window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('token', getToken() ?? '')
  return url.toString()
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url ?? ''
    // A 401 from the login endpoint means "wrong password", not "session
    // expired" — that one belongs to the form, not the global handler.
    const isLoginAttempt = url.includes('/auth/login') || url.includes('/auth/register')
    if (status === 401 && !isLoginAttempt) notifyUnauthorized()
    return Promise.reject(error)
  },
)

/** Turns an axios error into something worth showing a person. */
export function errorMessage(error, fallback = 'Something went wrong.') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  // FastAPI validation errors arrive as a list of {loc, msg, type}.
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0]
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : null
    return field ? `${field}: ${first.msg}` : first.msg
  }
  if (error?.response?.status === 401) return 'Incorrect email or password.'
  if (error?.code === 'ERR_NETWORK') return 'Cannot reach the backend. Is it running?'
  return error?.message ?? fallback
}

/**
 * The task as it currently stands if `error` is a version conflict (409) from
 * a task update, else null. The server sends it so the client can show the
 * latest state instead of the edit it refused.
 */
export function conflictTask(error) {
  return error?.response?.status === 409 ? (error.response.data?.current_task ?? null) : null
}

export async function getHealth() {
  const { data } = await api.get('/health')
  return data
}

export const auth = {
  async login(email, password) {
    const { data } = await api.post('/auth/login', { email, password })
    return data
  },
  async register(email, password) {
    const { data } = await api.post('/auth/register', { email, password })
    return data
  },
  async me() {
    const { data } = await api.get('/auth/me')
    return data
  },
}

export const workspaces = {
  async list() {
    const { data } = await api.get('/workspaces')
    return data
  },
  async create(name) {
    const { data } = await api.post('/workspaces', { name })
    return data
  },
  async get(id) {
    const { data } = await api.get(`/workspaces/${id}`)
    return data
  },
  async addMember(id, { userId, email, role }) {
    const body = userId ? { user_id: userId } : { email }
    if (role) body.role = role
    const { data } = await api.post(`/workspaces/${id}/members`, body)
    return data
  },
}

export const tasks = {
  async list(workspaceId) {
    const { data } = await api.get(`/workspaces/${workspaceId}/tasks`)
    return data
  },
  async create(workspaceId, payload) {
    const { data } = await api.post(`/workspaces/${workspaceId}/tasks`, payload)
    return data
  },
  /** Applies only if the task is still at `expectedVersion`; see conflictTask(). */
  async update(taskId, changes, expectedVersion) {
    const { data } = await api.patch(`/tasks/${taskId}`, {
      ...changes,
      expected_version: expectedVersion,
    })
    return data
  },
  async remove(taskId) {
    await api.delete(`/tasks/${taskId}`)
  },
}

export const comments = {
  async list(taskId) {
    const { data } = await api.get(`/tasks/${taskId}/comments`)
    return data
  },
  async create(taskId, body) {
    const { data } = await api.post(`/tasks/${taskId}/comments`, { body })
    return data
  },
}
