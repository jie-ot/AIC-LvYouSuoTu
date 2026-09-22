/**
 * 全局类型定义
 *
 * 严格对齐《数据结构与通信接口规范》。
 * - 对外 DTO（PostcardGroup / Postcard / Report / Plan / FileAsset / UploadedPhoto / ReportChartPoint）统一 camelCase
 * - ItineraryData 一支（trip_info / preparations / bookings / itinerary / schedule）统一 snake_case
 * 兼容升级只新增可选字段，不删除或改名旧字段。
 */

/* ---------------- 明信片组 (PostcardGroup) ---------------- */

export interface PostcardGroup {
  id: string
  tripId?: string | null
  location: string
  startDate: string | null
  endDate: string | null
  dateLabel: string
  coverImage: string
  postcards: Postcard[]
}

/* ---------------- 单张明信片 (Postcard) ---------------- */

export interface Postcard {
  id: string
  title: string
  imageUrl: string
  sourceAssetIds?: string[]
  renderMode?:
    | "ai_composite"
    | "local_fallback"
    | "local_no_text"
    | "legacy"
    | "ai_art_direction_v4"
    | "ai_art_direction_no_text"
    | "local_art_direction_v4"
    | "local_art_direction_no_text"
    | "ai_art_direction_v5"
    | "ai_art_direction_no_text_v5"
    | "local_art_direction_v5"
    | "local_art_direction_no_text_v5"
    | null
  promptVersion?: string | null
}

/* ---------------- 前端交给后端的单张照片信息 (UploadedPhoto) ---------------- */

export interface UploadedPhoto {
  assetId: string
  imageUrl: string
  takenAt: string | null
  location: string | null
}

/* ---------------- 文件资源 (FileAsset) ---------------- */

export interface FileAsset {
  id: string
  relativePath: string
  mimeType: string
  sizeBytes: number
  usageType: "upload" | "generated_postcard" | "generated_report_cover" | "system"
  status: "temporary" | "attached" | "deleted"
  refCount: number
}

/* ---------------- 旅行偏好报告 (Report) ---------------- */

export interface Report {
  id: string
  tripId?: string | null
  location: string
  startDate: string | null
  endDate: string | null
  dateLabel: string
  coverImage: string
  personalitySummary: string
  content: string
  chartData: ReportChartPoint[]
  profileVersion?: number | null
  profileData?: TravelProfileData | null
  sourceImages?: string[]
}

export type VisualTheme =
  | "forest_light"
  | "ocean_blue"
  | "sunset_orange"
  | "museum_gold"
  | "city_neon"
  | "night_purple"
  | "snow_silver"
  | "desert_amber"

export interface ProfileSpectrum {
  id: "environment" | "depth" | "planning" | "social"
  leftLabel: string
  rightLabel: string
  value: number
}

export interface ProfileTraitAssessment {
  id: "environment" | "depth" | "planning" | "social"
  value: number
  confidence: number
  evidenceRefs: string[]
  assessment: "supported" | "undetermined"
}

export interface SceneSignature {
  title: string
  tokens: string[]
  description: string
  evidenceRefs: string[]
}

export interface EvidenceHighlight {
  assetId: string
  imageUrl?: string | null
  observedFact: string
  traitId: "scene" | "environment" | "depth" | "planning" | "social"
  contribution: string
}

export interface NextTripExperiment {
  kind: "continue" | "contrast"
  title: string
  reason: string
  planningPrompt: string
  evidenceRefs: string[]
}

export interface ProfileModule {
  title: string
  content: string
}

export interface MusicRecommendation {
  title: string
  reason: string
  mood: string
}

export interface TravelProfileData {
  archetypeId: string
  archetypeName: string
  personaCode: string
  slogan: string
  summary?: string | null
  spectrums: ProfileSpectrum[]
  keywords: string[]
  modules: ProfileModule[]
  strengths?: string[]
  watchouts?: string[]
  bestScenarios?: string[]
  actionTips?: string[]
  nextTripInspiration: string
  musicRecommendation?: MusicRecommendation | null
  travelPrescription?: string | null
  souvenirLine?: string | null
  visualTheme: VisualTheme
  sampleQuality?: "low" | "medium" | "high"
  confidence?: number
  traits?: ProfileTraitAssessment[]
  scopeNote?: string
  explicitRequirements?: string[]
  sceneSignature?: SceneSignature | null
  evidenceHighlights?: EvidenceHighlight[]
  nextTripExperiments?: NextTripExperiment[]
  journeyCount?: number
  profileStage?: string
  returningMotifs?: string[]
  newFacets?: string[]
}

/* ---------------- 雷达图数据点 (ReportChartPoint) ---------------- */

export type RadarDimension = "自然探索" | "人文体验" | "美食偏好" | "慢节奏" | "社交意愿"

export interface ReportChartPoint {
  dimension: RadarDimension
  value: number
}

/* ---------------- 历史规划 (Plan) ---------------- */

export interface Plan {
  id: string
  tripId?: string | null
  location: string
  startDate: string | null
  endDate: string | null
  dateLabel: string
  content: string
  itineraryData: ItineraryData
}

export interface TripSummary {
  id: string
  title: string
  location: string | null
  startDate: string | null
  endDate: string | null
  dateLabel: string
  coverImage: string | null
  planCount: number
  postcardCount: number
  reportCount: number
  updatedAt: string
}

export interface TripDetail extends TripSummary {
  plans: Plan[]
  postcardGroups: PostcardGroup[]
  reports: Report[]
}

/* ---------------- 多轮旅行规划会话 ---------------- */

export type PlanningPhase = "collecting" | "confirming" | "completed"
export type PlanningModel =
  | "deepseek-v4-flash"
  | "deepseek-v4-pro"

export interface PlanningChatMessage {
  role: "user" | "assistant"
  content: string
  planningModel?: PlanningModel
}

export interface PlanningBrief {
  origin: string | null
  destinations: string[]
  startDate: string | null
  endDate: string | null
  travelerCount: number | null
  budget: string | null
  transportPreference: string | null
  lodgingPreference: string | null
  interests: string[]
  constraints: string[]
  assumptions: string[]
  summary: string
  /** Residual requirements not covered by the structured checklist rows. */
  detailRequirements?: string
}

export interface PlanningChecklistItem {
  key: string
  label: string
  value: string
  status: "ready" | "assumed" | "missing"
  required: boolean
}

export interface PlanningResponse {
  phase: PlanningPhase
  assistantMessage: string
  planningModel: PlanningModel
  brief: PlanningBrief | null
  checklist: PlanningChecklistItem[]
  confirmationToken: string | null
  itinerary: ItineraryData | null
}

/** 规划阶段。与后端 planning_progress 的 stage 取值一一对应。 */
export type PlanningProgressStage =
  | "queued"
  | "reading_memory"
  | "collecting_requirements"
  | "prefetching_facts"
  | "understanding_request"
  | "researching"
  | "research_complete"
  | "selecting_facts"
  | "synthesizing"
  | "verifying"
  | "finalizing"
  | "completed"
  | "failed"

export type PlanningProgressPhase =
  | "preparing"
  | "researching"
  | "composing"
  | "verifying"
  | "completed"
  | "failed"

/**
 * 生成过程中的真实后端进度快照（GET /ai/planning/progress）。
 * 规划本身仍是一次阻塞 POST，本快照只供待机动画展示，缺失时不影响出图。
 */
export interface PlanningProgressSnapshot {
  token: string
  stage: PlanningProgressStage
  stageLabel: string
  phase: PlanningProgressPhase
  percent: number
  detail: string | null
  elapsedMs: number
  estimatedTotalMs: number
  estimatedRemainingMs: number
  researchRound: number
  targetRounds: number
  maxRounds: number
  toolCallCount: number
  factCount: number
  repairRound: number
  planningModel: PlanningModel | null
  recentActivities: string[]
  error: string | null
  done: boolean
}

/* ---------------- 旅行记忆展示 (TravelMemory) ---------------- */

export interface TravelMemoryDescription {
  id: string
  icon: string
  title: string
  content: string
  planningHint?: string | null
  sourceLabels?: string[]
  editable: boolean
  state?: "candidate" | "active"
  origin?: "inferred" | "manual" | "explicit_requirement"
  confidence?: number
  confirmationText?: string | null
  legacyObservation?: boolean
  enabled?: boolean
  category?: string
  sourceTripId?: string | null
  sourceLabel?: string | null
}

export interface TravelMemoryPlanningPreference {
  key: "transport" | "hotel" | "attractions" | "food" | "pace" | "other"
  label: string
  value: string
  placeholder: string
  helper: string
  editable: boolean
}

export interface TravelMemoryStats {
  tripCount: number
  placeCount: number
  photoCount: number
  planCount: number
}

export interface TravelMemoryFootprint {
  id: string
  tripId: string
  title: string
  location?: string | null
  dateLabel: string
  coverImage?: string | null
  state: "recorded" | "planned" | "undated"
  stateLabel: string
  sourceLabels: string[]
  travelTypes: string[]
  highlights: string[]
  paceLabel?: string | null
  photoCount: number
  planCount: number
}

export interface TravelMemoryPattern {
  id: string
  title: string
  content: string
  category: string
  sourceKind: "photos" | "plans" | "combined"
  supportCount: number
  sourceTripIds: string[]
  sourceLabels: string[]
  confirmable: boolean
  confirmed: boolean
  planningText?: string | null
}

export interface TravelMemoryDisplay {
  intro: string | null
  overviewTitle?: string | null
  overviewContent?: string | null
  planningPreferences: TravelMemoryPlanningPreference[]
  memories: TravelMemoryDescription[]
  stats: TravelMemoryStats
  footprints: TravelMemoryFootprint[]
  patterns: TravelMemoryPattern[]
  editable: boolean
  updatedAt: string | null
  version: number
  isEmpty: boolean
  enabled?: boolean
  legacyCount?: number
}

/* ---------------- 结构化行程数据 (ItineraryData) ---------------- */

export interface ItineraryData {
  trip_info: TripInfo
  preparations: Preparation[]
  bookings: Booking[]
  food_recommendations: string[]
  itinerary: DailyItinerary[]
  experience_summary?: ExperienceSummary | null
  /** Gate-authored caveats for findings that are not tied to a single schedule row. */
  advisories?: string[]
}

export interface ExperienceSummary {
  tripTheme?: string
  pace?: string
  intensity?: number
  highlights?: string[]
  weatherSummary?: string
  personalizationTags?: string[]
}

export interface TripInfo {
  destination: string
  start_date: string
  end_date: string
  date_label: string
}

export interface Preparation {
  category: string
  items: string
}

export interface Booking {
  type: "机票" | "火车票" | "酒店" | "景区门票" | string
  details: string
}

export interface DailyItinerary {
  id: string
  date: string
  title?: string
  schedules: Schedule[]
  daily_maps?: DailyMap[]
}

export interface DailyMapPoint {
  schedule_id: string
  marker: string
  name: string
  location: string
  kind: "hotel" | "attraction"
}

export interface DailyMapLeg {
  origin_marker: string
  destination_marker: string
  transport_text: string
}

export interface DailyMap {
  id: string
  title: string
  image_url?: string | null
  status: "ready" | "unavailable"
  points: DailyMapPoint[]
  legs: DailyMapLeg[]
  line_note: string
}

export interface Schedule {
  id: string
  time_period: string
  start_time?: string | null
  end_time?: string | null
  activity: string
  transport?: string | null
  place_name?: string | null
  location?: string | null
  travel_minutes?: number | null
  distance_km?: number | null
  transport_mode?: "driving" | "transit" | "walking" | "bicycling" | null
  tags?: string[]
  booking_required?: boolean
  fact_status?: "verified" | "reference" | "unverified" | null
  fact_refs?: string[]
  action?: {
    type: "map" | "booking" | "details" | "alternative" | "complete"
    label: string
  } | null
  map_role?: "hotel" | "attraction" | null
  map_group?: string | null
  map_label?: string | null
}

/* ---------------- 业务状态码（前端展示用，对齐 0.6） ---------------- */

export type BusinessCode = 0 | 1001 | 1002 | 1003 | 1004

/* ---------------- 前端页面目的地（映射到 Next.js App Router URL） ---------------- */

export type PageType =
  | "home"
  | "trip-detail"
  | "memory"
  | "postcards"
  | "postcard-collection"
  | "reports"
  | "report-detail"
  | "planning"
  | "history"
  | "history-detail"
