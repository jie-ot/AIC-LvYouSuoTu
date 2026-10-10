"use client"

import { useEffect, useState, type FormEvent } from "react"
import { ArrowRight, Eye, EyeOff, LoaderCircle, Map, UserRound } from "lucide-react"
import { useAuth } from "@/components/shared/auth-context"
import { getAuthOptions } from "@/lib/auth-api"
import { friendlyMessage } from "@/lib/errors"

export function LoginView() {
  const { login, register, demo, entryMode } = useAuth()
  const [mode, setMode] = useState<"login" | "register">(entryMode)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [demoEnabled, setDemoEnabled] = useState(false)

  useEffect(() => {
    let cancelled = false
    void getAuthOptions().then((options) => { if (!cancelled) setDemoEnabled(options.demoEnabled) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setError("")
    if (mode === "register" && password !== confirmPassword) { setError("两次输入的密码不一致"); return }
    setBusy(true)
    try {
      await (mode === "register" ? register : login)(username.trim(), password)
    } catch (cause) { setError(friendlyMessage(cause)) } finally { setBusy(false) }
  }
  async function experience() {
    setError("")
    setBusy(true)
    try { await demo() } catch (cause) { setError(friendlyMessage(cause)) } finally { setBusy(false) }
  }

  return <main className="auth-page">
    <div className="auth-layout">
      <section className="auth-intro">
        <div className="brand-mark">旅有所图 / JOURNEY NOTES</div>
        <div className="auth-seal" aria-hidden><Map size={28} strokeWidth={1.3} /></div>
        <h1>每一程，<br />都值得留下来。</h1>
        <p>收藏旅行照片，留下自己的记忆，<br className="auth-desktop-break" />再为下一次出发做个计划。</p>
        <span className="auth-intro-note">照片 · 明信片 · 旅行记忆 · 下一程</span>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-tabs" role="tablist" aria-label="账号操作">
          {(["login", "register"] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={mode === item} disabled={busy} onClick={() => { setMode(item); setError(""); setConfirmPassword("") }}>{item === "login" ? "登录" : "注册"}</button>)}
        </div>
        <h2 id="auth-title">{mode === "login" ? "欢迎回来" : "创建你的账号"}</h2>
        <p className="auth-card-description">{mode === "login" ? "登录后，继续整理你的旅行。" : "用自己的账号，保存自己的旅行资料。"}</p>
        <form onSubmit={submit} className="auth-form">
          <label htmlFor="auth-username">用户名</label>
          <input id="auth-username" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} minLength={2} maxLength={24} value={username} onChange={(event) => setUsername(event.target.value)} disabled={busy} required placeholder="输入用户名" aria-describedby={mode === "register" ? "username-hint" : undefined} />
          {mode === "register" ? <small id="username-hint">2–24 个字，支持中文、字母、数字、_ 和 -</small> : null}
          <label htmlFor="auth-password">密码</label>
          <div className="auth-password">
            <input id="auth-password" name="password" type={visible ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} required placeholder={mode === "login" ? "输入密码" : "设置至少 8 位密码"} />
            <button type="button" onClick={() => setVisible((old) => !old)} aria-label={visible ? "隐藏密码" : "显示密码"} aria-pressed={visible}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button>
          </div>
          {mode === "register" ? <><label htmlFor="auth-confirm">确认密码</label><input id="auth-confirm" name="confirmPassword" type={visible ? "text" : "password"} autoComplete="new-password" minLength={8} maxLength={128} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} disabled={busy} required placeholder="再次输入密码" /></> : null}
          {error ? <p className="auth-error" role="alert">{error}</p> : null}
          <button type="submit" className="auth-submit" disabled={busy}>{busy ? <LoaderCircle size={18} className="animate-spin" aria-hidden /> : null}{busy ? "请稍候…" : mode === "login" ? "登录" : "注册并进入"}{busy ? null : <ArrowRight size={18} aria-hidden />}</button>
        </form>
        {demoEnabled ? <div className="auth-demo"><button type="button" onClick={() => { void experience() }} disabled={busy}><UserRound size={17} aria-hidden />体验演示账号<ArrowRight size={16} aria-hidden /></button><p>只读体验已有旅行、明信片和报告。<br />注册新账号后，你的资料独立保存。</p></div> : null}
      </section>
    </div>
  </main>
}
