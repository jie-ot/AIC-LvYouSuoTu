const UNRESOLVED_PLACES = new Set(["", "未知地点", "未知目的地", "旅行影像", "未命名旅行"])

/** A readable place line; never surfaces an unresolved-location marker. */
export function displayPlace(value: string | null | undefined, fallback?: string | null) {
  const place = (value ?? "").trim()
  if (!UNRESOLVED_PLACES.has(place)) return place
  const backup = (fallback ?? "").trim()
  return backup && !UNRESOLVED_PLACES.has(backup) ? backup : "沿途所见"
}
