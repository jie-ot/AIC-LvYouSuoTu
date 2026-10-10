/** Session credentials stay local and are never embedded in travel records. */
export interface Account {
  id: string
  username: string
  isDemo: boolean
  readOnly: boolean
}

export interface AuthSession {
  user: Account
  token: string
  mediaToken: string
  expiresAt: string
}

export const AUTH_STORAGE_KEY = "lvyousuotu:auth-session"
export const AUTH_CHANGED_EVENT = "lvyousuotu:auth-changed"
let currentSession: AuthSession | null | undefined

function validSession(value: unknown): value is AuthSession {
  if (!value || typeof value !== "object") return false
  const candidate = value as Partial<AuthSession>
  return typeof candidate.token === "string" && typeof candidate.mediaToken === "string"
    && typeof candidate.expiresAt === "string" && Boolean(candidate.user)
    && typeof candidate.user?.id === "string" && typeof candidate.user?.username === "string"
    && Date.parse(candidate.expiresAt) > Date.now()
}

export function readSession(): AuthSession | null {
  if (typeof window === "undefined") return null
  if (currentSession === undefined) {
    try {
      const value: unknown = JSON.parse(window.localStorage.getItem(AUTH_STORAGE_KEY) || "null")
      currentSession = validSession(value) ? value : null
    } catch { currentSession = null }
  }
  if (currentSession && Date.parse(currentSession.expiresAt) <= Date.now()) currentSession = null
  return currentSession
}

export function saveSession(session: AuthSession): void {
  currentSession = session
  try { window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session)) } catch { /* Memory-only login still works. */ }
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
}

/** A late 401 from an old request must not sign out a newly selected account. */
export function clearSession(expectedToken?: string | null): void {
  if (expectedToken !== undefined && (readSession()?.token ?? null) !== expectedToken) return
  currentSession = null
  try { window.localStorage.removeItem(AUTH_STORAGE_KEY) } catch { /* optional persistence */ }
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT))
}

export function refreshSessionFromStorage(): void {
  currentSession = undefined
}
