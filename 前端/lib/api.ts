/**
 * 业务 API 门面（唯一对外入口）。
 * View 与 AppProvider 只依赖本文件，所有请求由 real-api 和 http-client 统一处理。
 */
import type {
  ItineraryData,
  Plan,
  PlanningBrief,
  PlanningChatMessage,
  PlanningModel,
  PlanningProgressSnapshot,
  PlanningResponse,
  PostcardGroup,
  Report,
  TravelMemoryDisplay,
  TripDetail,
  TripSummary,
  UploadedPhoto,
} from "@/types"
import { realApi } from "./real-api"

export interface GenerateInput {
  photos: UploadedPhoto[]
  requirements: string
  memoryRequirements?: string
  clientRequestId?: string
  tripId?: string
  options: {
    generatePostcards: boolean
    generateReport: boolean
    postcardCount?: number
    learnPreferences?: boolean
  }
}

export interface GenerationWarning {
  code: string
  message: string
  feature: "postcard" | "report" | "memory" | "input" | "system"
  itemIndex?: number | null
  retryable: boolean
}

export interface GenerateResult {
  postcardGroup: PostcardGroup | null
  report: Report | null
  trip?: TripSummary | null
  operationId?: string | null
  status?: "completed" | "partial" | "failed"
  postcardStatus?: "success" | "failed" | "skipped"
  reportStatus?: "success" | "failed" | "skipped"
  memoryStatus?: "success" | "failed" | "skipped" | "pending"
  warnings?: GenerationWarning[]
}

export interface PlanWithAIInput {
  message: string
  planningModel: PlanningModel
  context: ItineraryData | null
  messages?: PlanningChatMessage[]
  brief?: PlanningBrief | null
  confirmed?: boolean
  /** Use confirmed travel memories for this planning request only. */
  useMemory?: boolean
  /** IDs excluded from this one run; saved memories stay intact. */
  excludedMemoryIds?: string[]
  /** Must match the latest server-authored confirmation checklist. */
  confirmationToken?: string | null
  /** 客户端生成的进度令牌；带上后可用 getPlanningProgress 轮询真实阶段。 */
  progressToken?: string
}

export interface MemoryOverviewUpdateInput {
  title: string
  content: string
  expectedVersion: number
}

export interface MemoryDescriptionUpdateInput {
  title: string
  content: string
  expectedVersion: number
}

export interface MemoryPlanningPreferencesUpdateInput {
  transport: string
  hotel: string
  attractions: string
  food: string
  pace: string
  other: string
  expectedVersion: number
}

/** 后端能力契约。 */
export interface TravelApi {
  // 初始化全量加载
  getPostcardGroups(): Promise<PostcardGroup[]>
  getReports(): Promise<Report[]>
  getPlans(): Promise<Plan[]>
  getTrips(): Promise<TripSummary[]>
  getTrip(id: string): Promise<TripDetail>
  createTrip(input: { title: string; location?: string | null }): Promise<TripSummary>
  updateTrip(id: string, input: { title: string }): Promise<TripSummary>
  deleteTrip(id: string): Promise<void>

  // 旅行后流
  uploadImage(file: File): Promise<{ assetId: string; imageUrl: string }>
  generateTravelArtifacts(input: GenerateInput): Promise<GenerateResult>

  // 旅行前流
  planWithAI(input: PlanWithAIInput): Promise<PlanningResponse>
  getPlanningProgress(token: string): Promise<PlanningProgressSnapshot | null>
  createPlan(input: { itineraryData: ItineraryData; tripId?: string }): Promise<Plan>
  updatePlan(id: string, input: { itineraryData: ItineraryData }): Promise<Plan>

  // 旅行记忆展示
  getTravelMemory(): Promise<TravelMemoryDisplay>
  updateTravelMemoryOverview(input: MemoryOverviewUpdateInput): Promise<TravelMemoryDisplay>
  updateTravelMemoryDescription(id: string, input: MemoryDescriptionUpdateInput): Promise<TravelMemoryDisplay>
  updateTravelMemoryPlanningPreferences(input: MemoryPlanningPreferencesUpdateInput): Promise<TravelMemoryDisplay>
  deleteTravelMemoryDescription(id: string, expectedVersion: number): Promise<TravelMemoryDisplay>
  createTravelMemoryItem(input: { text: string; category: string; expectedVersion: number }): Promise<TravelMemoryDisplay>
  patchTravelMemoryItem(id: string, input: { text?: string; category?: string; enabled?: boolean; confirm?: boolean; expectedVersion: number }): Promise<TravelMemoryDisplay>
  deleteTravelMemoryItem(id: string, expectedVersion: number): Promise<TravelMemoryDisplay>
  deleteTravelPhotoObservation(tripId: string, expectedVersion: number): Promise<TravelMemoryDisplay>
  updateTravelMemorySettings(input: { enabled: boolean; expectedVersion: number }): Promise<TravelMemoryDisplay>
  confirmTravelMemoryPattern(id: string, expectedVersion: number): Promise<TravelMemoryDisplay>

  // 删除
  deletePostcardGroup(id: string): Promise<void>
  deleteReport(id: string): Promise<void>
  deletePlan(id: string): Promise<void>
}

export function getPostcardGroups(): Promise<PostcardGroup[]> {
  return realApi.getPostcardGroups()
}
export function getReports(): Promise<Report[]> {
  return realApi.getReports()
}
export function getPlans(): Promise<Plan[]> {
  return realApi.getPlans()
}
export function getTrips(): Promise<TripSummary[]> {
  return realApi.getTrips()
}
export function getTrip(id: string): Promise<TripDetail> {
  return realApi.getTrip(id)
}
export function createTrip(input: { title: string; location?: string | null }): Promise<TripSummary> {
  return realApi.createTrip(input)
}
export function updateTrip(id: string, input: { title: string }): Promise<TripSummary> {
  return realApi.updateTrip(id, input)
}
export function deleteTrip(id: string): Promise<void> {
  return realApi.deleteTrip(id)
}
export function uploadImage(file: File): Promise<{ assetId: string; imageUrl: string }> {
  return realApi.uploadImage(file)
}
export function generateTravelArtifacts(input: GenerateInput): Promise<GenerateResult> {
  return realApi.generateTravelArtifacts(input)
}
export function planWithAI(input: PlanWithAIInput): Promise<PlanningResponse> {
  return realApi.planWithAI(input)
}
export function getPlanningProgress(token: string): Promise<PlanningProgressSnapshot | null> {
  return realApi.getPlanningProgress(token)
}
export function createPlan(input: { itineraryData: ItineraryData; tripId?: string }): Promise<Plan> {
  return realApi.createPlan(input)
}
export function updatePlan(id: string, input: { itineraryData: ItineraryData }): Promise<Plan> {
  return realApi.updatePlan(id, input)
}
export function getTravelMemory(): Promise<TravelMemoryDisplay> {
  return realApi.getTravelMemory()
}
export function updateTravelMemoryOverview(input: MemoryOverviewUpdateInput): Promise<TravelMemoryDisplay> {
  return realApi.updateTravelMemoryOverview(input)
}
export function updateTravelMemoryDescription(id: string, input: MemoryDescriptionUpdateInput): Promise<TravelMemoryDisplay> {
  return realApi.updateTravelMemoryDescription(id, input)
}
export function updateTravelMemoryPlanningPreferences(input: MemoryPlanningPreferencesUpdateInput): Promise<TravelMemoryDisplay> {
  return realApi.updateTravelMemoryPlanningPreferences(input)
}
export function deleteTravelMemoryDescription(id: string, expectedVersion: number): Promise<TravelMemoryDisplay> {
  return realApi.deleteTravelMemoryDescription(id, expectedVersion)
}
export function createTravelMemoryItem(input: { text: string; category: string; expectedVersion: number }): Promise<TravelMemoryDisplay> {
  return realApi.createTravelMemoryItem(input)
}
export function patchTravelMemoryItem(id: string, input: { text?: string; category?: string; enabled?: boolean; confirm?: boolean; expectedVersion: number }): Promise<TravelMemoryDisplay> {
  return realApi.patchTravelMemoryItem(id, input)
}
export function deleteTravelMemoryItem(id: string, expectedVersion: number): Promise<TravelMemoryDisplay> {
  return realApi.deleteTravelMemoryItem(id, expectedVersion)
}

export function deleteTravelPhotoObservation(tripId: string, expectedVersion: number): Promise<TravelMemoryDisplay> {
  return realApi.deleteTravelPhotoObservation(tripId, expectedVersion)
}
export function updateTravelMemorySettings(input: { enabled: boolean; expectedVersion: number }): Promise<TravelMemoryDisplay> {
  return realApi.updateTravelMemorySettings(input)
}
export function confirmTravelMemoryPattern(id: string, expectedVersion: number): Promise<TravelMemoryDisplay> {
  return realApi.confirmTravelMemoryPattern(id, expectedVersion)
}
export function deletePostcardGroup(id: string): Promise<void> {
  return realApi.deletePostcardGroup(id)
}
export function deleteReport(id: string): Promise<void> {
  return realApi.deleteReport(id)
}
export function deletePlan(id: string): Promise<void> {
  return realApi.deletePlan(id)
}
