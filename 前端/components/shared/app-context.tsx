"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import type { PluginListenerHandle } from "@capacitor/core"
import { usePathname, useRouter } from "next/navigation"
import type {
  BusinessCode,
  PageType,
  Plan,
  PlanningModel,
  PlanningResponse,
  PostcardGroup,
  Report,
  TripSummary,
} from "@/types"
import {
  createPlan,
  deletePlan as apiDeletePlan,
  deletePostcardGroup as apiDeletePostcardGroup,
  deleteReport as apiDeleteReport,
  generateTravelArtifacts,
  getPlans,
  getPostcardGroups,
  getReports,
  getTrips,
  planWithAI,
  updatePlan,
  uploadImage,
  type GenerateResult,
  type PlanWithAIInput,
} from "@/lib/api"
import { readPhotoMeta } from "@/lib/exif"
import { preparePhotoForUpload, UPLOAD_LIMIT_BYTES } from "@/lib/upload-photo"
import { AppError, CODE_MESSAGE, friendlyMessage, type BusinessErrorCode } from "@/lib/errors"
import type { ItineraryData, UploadedPhoto } from "@/types"

/* ---------------- Toast ---------------- */
export type ToastVariant = "success" | "error" | "info"
export interface ToastItem {
  id: string
  message: string
  variant: ToastVariant
}

/* ---------------- 导航栈 ---------------- */
interface NavEntry {
  page: PageType
  groupId?: string
  reportId?: string
  planId?: string
  tripId?: string
  from?: "trip" | "memory" | "report" | "postcard" | "history"
  sourceId?: string
}

function hrefForEntry(entry: NavEntry): string {
  switch (entry.page) {
    case "home":
      return "/"
    case "trip-detail":
      return `/trips/detail?tripId=${encodeURIComponent(entry.tripId ?? "")}`
    case "memory":
      return "/memory"
    case "postcards":
      return "/postcards"
    case "postcard-collection":
      return `/postcards/detail?groupId=${encodeURIComponent(entry.groupId ?? "")}${entry.from ? `&from=${entry.from}` : ""}${entry.tripId ? `&tripId=${encodeURIComponent(entry.tripId)}` : ""}`
    case "reports":
      return "/reports"
    case "report-detail":
      return `/reports/detail?reportId=${encodeURIComponent(entry.reportId ?? "")}${entry.from ? `&from=${entry.from}` : ""}${entry.tripId ? `&tripId=${encodeURIComponent(entry.tripId)}` : ""}`
    case "planning":
      return entry.planId ? `/planning?planId=${encodeURIComponent(entry.planId)}` : "/planning"
    case "history":
      return "/planning/history"
    case "history-detail":
      return `/planning/history/detail?planId=${encodeURIComponent(entry.planId ?? "")}${entry.from ? `&from=${entry.from}` : ""}${entry.tripId ? `&tripId=${encodeURIComponent(entry.tripId)}` : ""}`
  }
}

function parentHref(pathname: string): string {
  if (pathname === "/postcards/detail") return "/postcards"
  if (pathname === "/reports/detail") return "/reports"
  if (pathname === "/planning/history/detail") return "/planning/history"
  if (pathname === "/planning/history") return "/planning"
  if (pathname === "/trips/detail") return "/"
  return "/"
}

interface LoadErrorState {
  trips: boolean
  postcardGroups: boolean
  reports: boolean
  plans: boolean
}

export interface GenerateArtifactsInput {
  files: File[]
  requirements: string
  memoryRequirements?: string
  clientRequestId?: string
  replayOnly?: boolean
  tripId?: string
  options: {
    generatePostcards: boolean
    generateReport: boolean
    postcardCount?: number
    learnPreferences?: boolean
  }
}

export type GenerationPhase = "preparing" | "uploading" | "creating"

export interface GenerationProgress {
  phase: GenerationPhase
  completed: number
  total: number
  options: GenerateArtifactsInput["options"]
}

export interface PlanningSeed {
  text: string
  sourceLabel: string
  returnHref?: string
}

/* ---------------- 多图上传：并发限流 + 单张重试 ---------------- */
// 同时在传的最大张数：贴合浏览器单域名约 6 个并发连接的上限，避免瞬时请求过多互相拖累
const UPLOAD_CONCURRENCY = 5
// 单张上传失败的最大重试次数（仅对可恢复的 1003 抖动重试）
const UPLOAD_MAX_RETRY = 2

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/**
 * 生成一次规划请求的进度令牌。
 * 后端只接受 [A-Za-z0-9_-]，且长度不超过 64；随机段用于区分并发请求。
 */
function newProgressToken(): string {
  const random = Math.random().toString(36).slice(2, 10)
  return `plan-${Date.now().toString(36)}-${random}`
}

/**
 * 上传单张：读 EXIF（内部已容错，不抛错）后上传，失败按线性退避重试。
 * 仅对 AppError(1003)（网络/服务抖动等可恢复错误）重试；1002 等参数类错误立即失败，重试无意义。
 */
async function uploadPhotoWithRetry(file: File): Promise<UploadedPhoto> {
  const meta = await readPhotoMeta(file)
  const uploadFile = await preparePhotoForUpload(file)
  let lastErr: unknown
  for (let attempt = 0; attempt <= UPLOAD_MAX_RETRY; attempt++) {
    try {
      const { assetId, imageUrl } = await uploadImage(uploadFile)
      return {
        assetId, imageUrl, takenAt: meta.takenAt, location: meta.location,
        latitude: meta.latitude, longitude: meta.longitude, altitude: meta.altitude,
      }
    } catch (err) {
      lastErr = err
      const retryable = err instanceof AppError && err.code === 1003
      if (!retryable || attempt === UPLOAD_MAX_RETRY) throw err
      await delay(400 * (attempt + 1))
    }
  }
  throw lastErr
}

/**
 * 在并发上限内并行上传全部照片，结果保持与输入顺序一致。
 * 全有全无：任一张重试后仍失败即整体抛错，绝不静默丢图（保证「选了什么就用什么」）。
 */
async function uploadAllPhotos(
  files: File[],
  onProgress?: (completed: number, total: number) => void,
): Promise<UploadedPhoto[]> {
  const results = new Array<UploadedPhoto>(files.length)
  let cursor = 0
  let completed = 0
  const worker = async () => {
    while (cursor < files.length) {
      const index = cursor++
      results[index] = await uploadPhotoWithRetry(files[index])
      completed += 1
      onProgress?.(completed, files.length)
    }
  }
  // Decoding several oversized photos at once can exhaust mobile WebView memory.
  const concurrency = files.some((file) => file.size > UPLOAD_LIMIT_BYTES) ? 2 : UPLOAD_CONCURRENCY
  const workerCount = Math.min(concurrency, files.length)
  await Promise.all(Array.from({ length: workerCount }, worker))
  return results
}

interface AppContextValue {
  // 导航
  navigate: (entry: NavEntry) => void
  goBack: () => void
  goBackTo: (href: string) => void
  registerBackHandler: (handler: () => void) => () => void
  // 数据
  postcardGroups: PostcardGroup[]
  reports: Report[]
  plans: Plan[]
  trips: TripSummary[]
  deletePostcardGroup: (id: string) => Promise<void>
  deleteReport: (id: string) => Promise<void>
  deletePlan: (id: string) => Promise<void>
  deletingId: string | null
  upsertPlan: (plan: Plan) => void
  prependPostcardGroup: (group: PostcardGroup) => void
  prependReport: (report: Report) => void
  upsertTrip: (trip: TripSummary) => void
  removeTrip: (id: string) => void
  // 首页生成流程
  generating: boolean
  generationProgress: GenerationProgress | null
  generateArtifacts: (input: GenerateArtifactsInput) => Promise<GenerateResult | null>
  // 旅行规划草稿（本地单一数据源，规范 §10）
  draftItineraryData: ItineraryData | null
  editingPlanId: string | null
  hasUnsavedDraft: boolean
  planning: boolean
  /** 当前（或最近一次）规划请求的进度令牌，供待机动画轮询真实进度。 */
  planningProgressToken: string | null
  planningTurn: (input: PlanWithAIInput) => Promise<PlanningResponse | null>
  planRefine: (message: string, planningModel: PlanningModel) => Promise<ItineraryData | null>
  planningSeed: PlanningSeed | null
  startPlanningFromSeed: (seed: PlanningSeed) => void
  clearPlanningSeed: () => void
  beginNewPlan: (tripId?: string | null) => void
  beginEditPlan: (plan: Plan) => void
  updateDraft: (data: ItineraryData) => void
  discardDraft: () => void
  saving: boolean
  savePlan: () => Promise<Plan | null>
  planningTripId: string | null
  // 初始化加载状态
  initLoading: boolean
  loadError: LoadErrorState
  reloadAll: () => void
  // 反馈
  toasts: ToastItem[]
  toast: (message: string, variant?: ToastVariant) => void
  toastCode: (code: Exclude<BusinessCode, 0>) => void
  toastError: (err: unknown) => void
  dismissToast: (id: string) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const navigationDepth = useRef(0)
  const pathnameRef = useRef(pathname)
  const goBackRef = useRef<() => void>(() => undefined)
  const backHandlers = useRef<Array<() => void>>([])
  const [postcardGroups, setPostcardGroups] = useState<PostcardGroup[]>([])
  const [reports, setReports] = useState<Report[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [trips, setTrips] = useState<TripSummary[]>([])
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [generating, setGenerating] = useState(false)
  const [generationProgress, setGenerationProgress] = useState<GenerationProgress | null>(null)
  const [draftItineraryData, setDraftItineraryData] = useState<ItineraryData | null>(null)
  const [editingPlanId, setEditingPlanId] = useState<string | null>(null)
  const [hasUnsavedDraft, setHasUnsavedDraft] = useState(false)
  const [planning, setPlanning] = useState(false)
  const [planningProgressToken, setPlanningProgressToken] = useState<string | null>(null)
  const [planningSeed, setPlanningSeed] = useState<PlanningSeed | null>(null)
  const [saving, setSaving] = useState(false)
  const [planningTripId, setPlanningTripId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [initLoading, setInitLoading] = useState(true)
  const [loadError, setLoadError] = useState<LoadErrorState>({
    trips: false,
    postcardGroups: false,
    reports: false,
    plans: false,
  })
  // Bumps when a plan is saved locally so an in-flight loadAll cannot
  // overwrite the just-saved list with the older server snapshot.
  const plansWriteEpochRef = useRef(0)

  useEffect(() => {
    const handlePopState = () => {
      navigationDepth.current = Math.max(0, navigationDepth.current - 1)
    }
    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [])

  const navigate = useCallback(
    (next: NavEntry) => {
      navigationDepth.current += 1
      router.push(hrefForEntry(next))
    },
    [router],
  )

  const goBack = useCallback(() => {
    if (navigationDepth.current > 0) {
      router.back()
      return
    }
    router.replace(parentHref(pathname))
  }, [pathname, router])

  const goBackTo = useCallback((href: string) => {
    router.replace(href)
  }, [router])

  const registerBackHandler = useCallback((handler: () => void) => {
    backHandlers.current.push(handler)
    return () => {
      const index = backHandlers.current.lastIndexOf(handler)
      if (index >= 0) backHandlers.current.splice(index, 1)
    }
  }, [])

  useEffect(() => {
    pathnameRef.current = pathname
    goBackRef.current = goBack
  }, [goBack, pathname])

  useEffect(() => {
    // Capacitor patches document.documentElement on import. Keep it inside
    // useEffect so the SSR markup can hydrate before any platform classes land.
    let cancelled = false
    let listener: PluginListenerHandle | null = null

    void (async () => {
      const { Capacitor } = await import("@capacitor/core")
      const { App: CapacitorApp } = await import("@capacitor/app")
      if (Capacitor.getPlatform() !== "android" || !Capacitor.isPluginAvailable("App")) return

      const handle = await CapacitorApp.addListener("backButton", () => {
        const handler = backHandlers.current[backHandlers.current.length - 1]
        if (handler) {
          handler()
          return
        }
        if (pathnameRef.current === "/") {
          void CapacitorApp.exitApp()
          return
        }
        goBackRef.current()
      })
      if (cancelled) {
        void handle.remove()
        return
      }
      listener = handle
    })()

    return () => {
      cancelled = true
      if (listener) void listener.remove()
    }
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts((t) => t.filter((x) => x.id !== id))
  }, [])

  const toast = useCallback(
    (message: string, variant: ToastVariant = "info") => {
      const id = Math.random().toString(36).slice(2, 9)
      setToasts((t) => [...t, { id, message, variant }])
      setTimeout(() => dismissToast(id), 2600)
    },
    [dismissToast],
  )

  const toastCode = useCallback(
    (code: Exclude<BusinessCode, 0>) => {
      toast(CODE_MESSAGE[code as BusinessErrorCode], code === 1002 ? "info" : "error")
    },
    [toast],
  )

  // 统一业务错误提示：AppError 走友好文案，1002 走后端字段提示；不暴露内部细节
  const toastError = useCallback(
    (err: unknown) => {
      toast(friendlyMessage(err), "error")
    },
    [toast],
  )

  /* ---------------- 初始化全量加载（规范 2.1 / §8） ---------------- */
  const loadAll = useCallback(async () => {
    setInitLoading(true)
    const plansEpoch = plansWriteEpochRef.current
    const [tripRes, pgRes, rptRes, planRes] = await Promise.allSettled([
      getTrips(),
      getPostcardGroups(),
      getReports(),
      getPlans(),
    ])

    const nextError: LoadErrorState = { trips: false, postcardGroups: false, reports: false, plans: false }

    if (tripRes.status === "fulfilled") {
      setTrips(tripRes.value)
    } else {
      nextError.trips = true
    }

    if (pgRes.status === "fulfilled") {
      setPostcardGroups(pgRes.value)
    } else {
      nextError.postcardGroups = true
    }

    if (rptRes.status === "fulfilled") {
      setReports(rptRes.value)
    } else {
      nextError.reports = true
    }

    if (planRes.status === "fulfilled") {
      if (plansWriteEpochRef.current === plansEpoch) {
        setPlans(planRes.value)
      }
    } else {
      nextError.plans = true
    }

    setLoadError(nextError)
    // 单接口失败不白屏：成功项已渲染，失败项给出统一提示（不暴露内部细节）
    if (nextError.trips || nextError.postcardGroups || nextError.reports || nextError.plans) {
      toast("部分内容加载失败，请重试", "error")
    }
    setInitLoading(false)
  }, [toast])

  // 避免 React StrictMode 下重复加载
  const didInit = useRef(false)
  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    void loadAll()
  }, [loadAll])

  const reloadAll = useCallback(() => {
    void loadAll()
  }, [loadAll])

  /* ---------------- 删除流程（规范 §11，等响应再移除） ---------------- */
  // 1004：内容已被删除 → 仍从本地列表移除并提示；其他错误：保留本地数据并提示失败
  const refreshTrips = useCallback(() => {
    void getTrips().then(setTrips).catch(() => undefined)
  }, [])

  const deletePostcardGroup = useCallback(
    async (id: string) => {
      setDeletingId(id)
      try {
        await apiDeletePostcardGroup(id)
        setPostcardGroups((g) => g.filter((x) => x.id !== id))
        refreshTrips()
        toast("已删除", "success")
      } catch (err) {
        if (err instanceof AppError && err.code === 1004) {
          setPostcardGroups((g) => g.filter((x) => x.id !== id))
          refreshTrips()
          toast(CODE_MESSAGE[1004], "info")
        } else {
          toastError(err)
        }
      } finally {
        setDeletingId(null)
      }
    },
    [refreshTrips, toast, toastError],
  )

  const deleteReport = useCallback(
    async (id: string) => {
      setDeletingId(id)
      try {
        await apiDeleteReport(id)
        setReports((r) => r.filter((x) => x.id !== id))
        refreshTrips()
        toast("已删除", "success")
      } catch (err) {
        if (err instanceof AppError && err.code === 1004) {
          setReports((r) => r.filter((x) => x.id !== id))
          refreshTrips()
          toast(CODE_MESSAGE[1004], "info")
        } else {
          toastError(err)
        }
      } finally {
        setDeletingId(null)
      }
    },
    [refreshTrips, toast, toastError],
  )

  const deletePlan = useCallback(
    async (id: string) => {
      setDeletingId(id)
      try {
        await apiDeletePlan(id)
        setPlans((p) => p.filter((x) => x.id !== id))
        refreshTrips()
        toast("行程已删除", "success")
      } catch (err) {
        if (err instanceof AppError && err.code === 1004) {
          setPlans((p) => p.filter((x) => x.id !== id))
          refreshTrips()
          toast(CODE_MESSAGE[1004], "info")
        } else {
          toastError(err)
        }
      } finally {
        setDeletingId(null)
      }
    },
    [refreshTrips, toast, toastError],
  )

  const upsertPlan = useCallback((plan: Plan) => {
    setPlans((p) => {
      const exists = p.some((x) => x.id === plan.id)
      return exists ? p.map((x) => (x.id === plan.id ? plan : x)) : [plan, ...p]
    })
  }, [])

  const prependPostcardGroup = useCallback((group: PostcardGroup) => {
    setPostcardGroups((g) => [group, ...g])
  }, [])

  const prependReport = useCallback((report: Report) => {
    setReports((r) => [report, ...r])
  }, [])

  const upsertTrip = useCallback((trip: TripSummary) => {
    setTrips((items) => [trip, ...items.filter((item) => item.id !== trip.id)])
  }, [])

  const removeTrip = useCallback((id: string) => {
    setTrips((items) => items.filter((item) => item.id !== id))
  }, [])

  /* ---------------- 首页生成流程（规范 2.2 / §9） ---------------- */
  const generateArtifacts = useCallback(
    async ({
      files,
      requirements,
      memoryRequirements,
      clientRequestId,
      replayOnly = false,
      tripId,
      options,
    }: GenerateArtifactsInput): Promise<GenerateResult | null> => {
      setGenerating(true)
      setGenerationProgress({
        phase: "preparing",
        completed: 0,
        total: files.length,
        options,
      })
      try {
        // 每张照片：读 EXIF（失败置 null，不报错）→ 上传 → 拼装 UploadedPhoto
        // 上传走并发限流 + 单张重试（详见 uploadAllPhotos），支持一次最多 50 张且更抗抖动
        setGenerationProgress({
          phase: "uploading",
          completed: 0,
          total: files.length,
          options,
        })
        const photos = await uploadAllPhotos(files, (completed, total) => {
          setGenerationProgress({
            phase: "uploading",
            completed,
            total,
            options,
          })
        })

        setGenerationProgress({
          phase: "creating",
          completed: files.length,
          total: files.length,
          options,
        })
        const result = await generateTravelArtifacts({
          photos,
          requirements,
          memoryRequirements,
          options,
          clientRequestId: clientRequestId ?? crypto.randomUUID(),
          tripId,
        })
        // 固定返回 { postcardGroup, report }；通过 if 判断追加，不依赖字段缺失
        if (!replayOnly && result.postcardGroup) {
          setPostcardGroups((g) => [result.postcardGroup as PostcardGroup, ...g])
        }
        if (!replayOnly && result.report) {
          setReports((r) => [result.report as Report, ...r])
        }
        if (result.trip) upsertTrip(result.trip)
        for (const warning of result.warnings ?? []) {
          toast(warning.message, "info")
        }
        if (result.status === "partial") {
          toast("已生成的内容已保存；其余内容可稍后重试", "info")
        }
        return result
      } catch (err) {
        toastError(err)
        return null
      } finally {
        setGenerating(false)
        setGenerationProgress(null)
      }
    },
    [toast, toastError, upsertTrip],
  )

  /* ---------------- 旅行规划对话流程（规范 2.3 / §10） ---------------- */
  // 需求澄清与确认共用一个入口；只有 completed 响应才写入行程草稿。
  // 每一轮都自带进度令牌：POST 仍是单次阻塞请求，待机动画另起轮询读取真实阶段。
  const planningTurn = useCallback(
    async (input: PlanWithAIInput): Promise<PlanningResponse | null> => {
      const token = input.progressToken ?? newProgressToken()
      setPlanningProgressToken(token)
      setPlanning(true)
      try {
        const response = await planWithAI({ ...input, progressToken: token })
        if (response.itinerary) {
          setDraftItineraryData(response.itinerary)
          if (!input.context) setEditingPlanId(null)
          setHasUnsavedDraft(true)
        }
        return response
      } catch (err) {
        toastError(err)
        return null
      } finally {
        setPlanning(false)
      }
    },
    [toastError],
  )

  // 已生成行程的后续打磨仍视为用户对当前版本的明确修改请求。
  const planRefine = useCallback(
    async (message: string, planningModel: PlanningModel): Promise<ItineraryData | null> => {
      if (!draftItineraryData) return null
      const response = await planningTurn({
        message,
        planningModel,
        context: draftItineraryData,
        messages: [{ role: "user", content: message, planningModel }],
        confirmed: true,
        useMemory: draftItineraryData.memory_context?.enabled ?? true,
        excludedMemoryIds: draftItineraryData.memory_context?.excluded_ids ?? [],
      })
      return response?.itinerary ?? null
    },
    [draftItineraryData, planningTurn],
  )

  // 全新规划：清空草稿与编辑态
  const beginNewPlan = useCallback((tripId?: string | null) => {
    setDraftItineraryData(null)
    setEditingPlanId(null)
    setHasUnsavedDraft(false)
    setPlanningSeed(null)
    setPlanningTripId(tripId ?? null)
  }, [])

  const startPlanningFromSeed = useCallback((seed: PlanningSeed) => {
    setDraftItineraryData(null)
    setEditingPlanId(null)
    setHasUnsavedDraft(false)
    setPlanningSeed(seed)
    setPlanningTripId(null)
  }, [])

  const clearPlanningSeed = useCallback(() => setPlanningSeed(null), [])

  // 继续编辑历史规划：从缓存载入 itineraryData（零网络），记住 plan.id，载入即视为未改动
  const beginEditPlan = useCallback((plan: Plan) => {
    setDraftItineraryData(JSON.parse(JSON.stringify(plan.itineraryData)) as ItineraryData)
    setEditingPlanId(plan.id)
    setHasUnsavedDraft(false)
    setPlanningTripId(plan.tripId ?? null)
  }, [])

  // 本地内联编辑同步到草稿（保留稳定 id，由调用方保证）
  const updateDraft = useCallback((data: ItineraryData) => {
    setDraftItineraryData({ ...data, planning_snapshot: null })
    setHasUnsavedDraft(true)
  }, [])

  const discardDraft = useCallback(() => {
    setDraftItineraryData(null)
    setEditingPlanId(null)
    setHasUnsavedDraft(false)
    setPlanningTripId(null)
  }, [])

  // 保存规划：无 editingPlanId → 新建；有 → 覆盖更新（规范 2.3 / §10.3-10.4）
  const savePlan = useCallback(async (): Promise<Plan | null> => {
    if (!draftItineraryData) return null
    setSaving(true)
    try {
      let plan: Plan
      if (editingPlanId) {
        plan = await updatePlan(editingPlanId, { itineraryData: draftItineraryData })
        plansWriteEpochRef.current += 1
        setPlans((p) => p.map((x) => (x.id === plan.id ? plan : x)))
      } else {
        plan = await createPlan({
          itineraryData: draftItineraryData,
          tripId: planningTripId ?? undefined,
        })
        plansWriteEpochRef.current += 1
        setPlans((p) => [plan, ...p])
      }
      // 用后端加工后的实体回写草稿，后续编辑视为针对该已保存规划
      setEditingPlanId(plan.id)
      setDraftItineraryData(plan.itineraryData)
      setHasUnsavedDraft(false)
      void getTrips().then(setTrips).catch(() => undefined)
      return plan
    } catch (err) {
      toastError(err)
      return null
    } finally {
      setSaving(false)
    }
  }, [draftItineraryData, editingPlanId, planningTripId, toastError])

  const value = useMemo<AppContextValue>(
    () => ({
      navigate,
      goBack,
      goBackTo,
      registerBackHandler,
      postcardGroups,
      reports,
      plans,
      trips,
      deletePostcardGroup,
      deleteReport,
      deletePlan,
      deletingId,
      upsertPlan,
      prependPostcardGroup,
      prependReport,
      upsertTrip,
      removeTrip,
      generating,
      generationProgress,
      generateArtifacts,
      draftItineraryData,
      editingPlanId,
      hasUnsavedDraft,
      planning,
      planningProgressToken,
      planningTurn,
      planRefine,
      planningSeed,
      startPlanningFromSeed,
      clearPlanningSeed,
      beginNewPlan,
      beginEditPlan,
      updateDraft,
      discardDraft,
      saving,
      savePlan,
      planningTripId,
      initLoading,
      loadError,
      reloadAll,
      toasts,
      toast,
      toastCode,
      toastError,
      dismissToast,
    }),
    [
      navigate,
      goBack,
      goBackTo,
      registerBackHandler,
      postcardGroups,
      reports,
      plans,
      trips,
      deletePostcardGroup,
      deleteReport,
      deletePlan,
      deletingId,
      upsertPlan,
      prependPostcardGroup,
      prependReport,
      upsertTrip,
      removeTrip,
      generating,
      generationProgress,
      generateArtifacts,
      draftItineraryData,
      editingPlanId,
      hasUnsavedDraft,
      planning,
      planningProgressToken,
      planningTurn,
      planRefine,
      planningSeed,
      startPlanningFromSeed,
      clearPlanningSeed,
      beginNewPlan,
      beginEditPlan,
      updateDraft,
      discardDraft,
      saving,
      savePlan,
      planningTripId,
      initLoading,
      loadError,
      reloadAll,
      toasts,
      toast,
      toastCode,
      toastError,
      dismissToast,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error("useApp must be used within AppProvider")
  return ctx
}
