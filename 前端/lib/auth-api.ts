import { apiClient, jsonInit } from "./http-client"
import type { Account, AuthSession } from "./auth-session"

export const getAuthOptions = () => apiClient<{ demoEnabled: boolean; demoUsername: string }>("/auth/options")
export const getCurrentAccount = () => apiClient<Account>("/auth/me")
export const loginAccount = (username: string, password: string) =>
  apiClient<AuthSession>("/auth/login", jsonInit("POST", { username, password }))
export const registerAccount = (username: string, password: string) =>
  apiClient<AuthSession>("/auth/register", jsonInit("POST", { username, password }))
export const loginDemo = () => apiClient<AuthSession>("/auth/demo", jsonInit("POST"))
export const logoutAccount = () => apiClient<null>("/auth/logout", jsonInit("POST"))
