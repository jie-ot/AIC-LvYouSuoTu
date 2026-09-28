import { apiClient, jsonInit } from "@/lib/http-client"

export const DISCOVERY_TAGS = ["自然", "海边", "城市漫步", "人文", "美食", "摄影", "徒步", "自驾", "公共交通", "慢旅行", "周末", "省心省钱"]
export type FeedMode = "recommended" | "saved" | "mine" | "hidden"
export interface SharedReport { id: string; title: string; summary: string; content: string; chartData: unknown[] }
export interface SharedPostcard { id: string; title: string; imageUrl: string }
export interface SharedPlan { id: string; title: string; destination: string; days: { day: number; title: string; stops: string[] }[] }
export interface Attachments { reports?: SharedReport[]; postcards?: SharedPostcard[]; plans?: SharedPlan[]; demoNotice?: string; coverCredit?: { author: string; url: string } }
export interface DiscoveryCard {
  id: string; title: string; destination: string; excerpt: string; author: string
  cover: string | null; tags: string[]; isDemo: boolean; isOwn: boolean
  saved: boolean; dismissed: boolean; createdAt: string; attachmentKinds: string[]; reasons: string[]
}
export interface DiscoveryPost extends DiscoveryCard {
  body: string; recommendations: string; pitfalls: string; photos: string[]; attachments: Attachments
}
export interface Feed {
  items: DiscoveryCard[]; total: number; nextOffset: number | null; demoCount: number
  semantic?: { status: "disabled" | "building" | "ready" | "unavailable"; dimensions?: number; interestCount?: number }
  profile: {
    destination: string; explicitTags: string[]; memoryTags: string[]; visitedCount: number
    plannedDestinations: string[]; personaTripCount: number; historyEnabled: boolean
  }
}
export interface ShareOptions {
  trip: { id: string; title: string; destination: string }
  photos: { id: string; url: string }[]
  reports: SharedReport[]; postcards: SharedPostcard[]; plans: SharedPlan[]
}
export interface ShareInput {
  requestId: string; tripId: string; title: string; destination: string; body: string
  recommendations: string; pitfalls: string; tags: string[]; photoAssetIds: string[]
  reportIds: string[]; postcardIds: string[]; planIds: string[]
}
export interface AssistResult { title: string; body: string; tags: string[]; source: "ai" | "rules"; message: string }

export function getDiscoveryFeed(q: string, topic: string, mode: FeedMode, offset = 0, useSemantic = true) {
  const params = new URLSearchParams({ q, topic, mode, offset: String(offset), limit: "20", use_semantic: String(useSemantic) })
  return apiClient<Feed>("/discovery/feed?" + params.toString())
}
export function getDiscoveryPost(id: string) { return apiClient<DiscoveryPost>("/discovery/posts/" + encodeURIComponent(id)) }
export function recordDiscoverySearch(query: string) {
  return apiClient<null>("/discovery/searches", jsonInit("POST", { query }))
}
export function discoveryFeedback(id: string, action: "save" | "unsave" | "dismiss" | "restore") {
  return apiClient<{ saved: boolean; dismissed: boolean }>("/discovery/posts/" + encodeURIComponent(id) + "/feedback", jsonInit("PUT", { action }))
}
export function getShareOptions(tripId: string) { return apiClient<ShareOptions>("/discovery/share-options?trip_id=" + encodeURIComponent(tripId)) }
export function publishDiscoveryPost(input: ShareInput) { return apiClient<DiscoveryPost>("/discovery/posts", jsonInit("POST", input)) }
export function withdrawDiscoveryPost(id: string) { return apiClient<null>("/discovery/posts/" + encodeURIComponent(id), jsonInit("DELETE")) }
export function assistDiscoveryNote(input: Pick<ShareInput, "destination" | "title" | "body" | "recommendations" | "pitfalls">) {
  const { destination, title, body, recommendations, pitfalls } = input
  return apiClient<AssistResult>("/discovery/assist", jsonInit("POST", { destination, title, body, recommendations, pitfalls }))
}
