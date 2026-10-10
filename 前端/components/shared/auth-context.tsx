"use client"

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { useRouter } from "next/navigation"
import { getCurrentAccount, loginAccount, loginDemo, logoutAccount, registerAccount } from "@/lib/auth-api"
import {
  AUTH_CHANGED_EVENT, AUTH_STORAGE_KEY, clearSession, readSession,
  refreshSessionFromStorage, saveSession, type Account, type AuthSession,
} from "@/lib/auth-session"
import { AppError, friendlyMessage } from "@/lib/errors"
import { AppProvider } from "./app-context"
import { LoginView } from "../views/login-view"

type AuthStatus = "loading" | "authenticated" | "anonymous" | "error"
interface AuthContextValue {
  user: Account | null
  session: AuthSession | null
  status: AuthStatus
  error: string
  entryMode: "login" | "register"
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  demo: () => Promise<void>
  logout: (mode?: "login" | "register") => Promise<void>
  retry: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [session, setSession] = useState<AuthSession | null>(null)
  const [status, setStatus] = useState<AuthStatus>("loading")
  const [error, setError] = useState("")
  const [entryMode, setEntryMode] = useState<"login" | "register">("login")
  const validation = useRef(0)

  const verifySession = useCallback(async () => {
    const epoch = ++validation.current
    const saved = readSession()
    setSession(saved)
    setError("")
    if (!saved) { setStatus("anonymous"); return }
    setStatus("loading")
    try {
      const user = await getCurrentAccount()
      if (epoch !== validation.current || readSession()?.token !== saved.token) return
      if (user.id !== saved.user.id) { clearSession(saved.token); return }
      setSession({ ...saved, user })
      setStatus("authenticated")
    } catch (cause) {
      if (epoch !== validation.current) return
      if (cause instanceof AppError && cause.code === 1005) {
        clearSession(saved.token)
        setSession(null)
        setStatus("anonymous")
      } else {
        setError(friendlyMessage(cause))
        setStatus("error")
      }
    }
  }, [])

  const invalidate = useCallback(() => { validation.current++ }, [])
  useEffect(() => {
    const initial = window.setTimeout(() => { void verifySession() }, 0)
    const changed = () => { void verifySession() }
    const storageChanged = (event: StorageEvent) => {
      if (event.key === AUTH_STORAGE_KEY || event.key === null) {
        refreshSessionFromStorage()
        changed()
      }
    }
    window.addEventListener(AUTH_CHANGED_EVENT, changed)
    window.addEventListener("storage", storageChanged)
    return () => {
      window.clearTimeout(initial)
      invalidate()
      window.removeEventListener(AUTH_CHANGED_EVENT, changed)
      window.removeEventListener("storage", storageChanged)
    }
  }, [verifySession, invalidate])

  const enter = useCallback((next: AuthSession) => {
    saveSession(next)
    router.replace("/")
  }, [router])
  const login = useCallback(async (username: string, password: string) => {
    enter(await loginAccount(username, password))
  }, [enter])
  const register = useCallback(async (username: string, password: string) => {
    enter(await registerAccount(username, password))
  }, [enter])
  const demo = useCallback(async () => { enter(await loginDemo()) }, [enter])
  const logout = useCallback(async (mode: "login" | "register" = "login") => {
    setEntryMode(mode)
    const token = readSession()?.token
    try { await logoutAccount() } finally {
      clearSession(token)
      router.replace("/")
    }
  }, [router])

  return <AuthContext.Provider value={{
    user: session?.user ?? null, session, status, error, entryMode, login, register, demo, logout,
    retry: () => { void verifySession() },
  }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error("useAuth must be used inside AuthProvider")
  return value
}

export function AuthGate({ children }: { children: ReactNode }) {
  const { status, session, error, retry, logout } = useAuth()
  if (status === "loading") return <main className="auth-wait" role="status"><span className="brand-mark">旅有所图</span><p>正在确认登录状态…</p></main>
  if (status === "error") return <main className="auth-wait"><span className="brand-mark">旅有所图</span><h1>暂时无法连接</h1><p role="alert">{error}</p><button className="primary-action" onClick={retry}>重新连接</button><button className="auth-text-button" onClick={() => { void logout().catch(() => undefined) }}>返回登录</button></main>
  if (status !== "authenticated" || !session) return <LoginView />
  return <AppProvider key={session.token}><div className="authenticated-app">
    {session.user.readOnly ? <div className="demo-notice" role="note"><span>只读演示 · 原有资料仅供浏览</span><button type="button" onClick={() => { void logout("register").catch(() => undefined) }}>注册自己的账号</button></div> : null}
    <div className="authenticated-pages">{children}</div>
  </div></AppProvider>
}
