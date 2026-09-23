/**
 * 照片 EXIF 元信息读取。
 *
 * 规范要求（《数据结构与通信接口规范》1.3 / 《前端真实能力接入规范》9）：
 * - takenAt：从 EXIF 拍摄时间读取相机当地钟点；读不到传 null。
 * - latitude / longitude / altitude：EXIF GPS 原始 WGS-84 坐标，交给后端逆地理解析为地名。
 * - location：兼容旧后端的坐标文本；读不到传 null。
 *
 * 服务端保存时会剥离 EXIF，所以这里是时间与地点的唯一来源。
 * 任何解析失败都返回 null，绝不抛错（不阻塞上传与生成流程）。
 */
import exifr from "exifr"

export interface PhotoMeta {
  takenAt: string | null
  location: string | null
  latitude: number | null
  longitude: number | null
  altitude: number | null
}

function toCameraTime(value: unknown): string | null {
  if (!value) return null
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null
    // EXIF DateTimeOriginal usually has no timezone. Keep the camera's wall
    // clock instead of converting it to UTC and shifting morning into night.
    const pad = (part: number) => String(part).padStart(2, "0")
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}`
  }
  if (typeof value === "string") {
    const match = /^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(value)
    return match ? `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}` : null
  }
  return null
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export async function readPhotoMeta(file: File): Promise<PhotoMeta> {
  const meta: PhotoMeta = { takenAt: null, location: null, latitude: null, longitude: null, altitude: null }

  try {
    const tags = await exifr.parse(file, ["DateTimeOriginal", "CreateDate", "GPSAltitude", "GPSAltitudeRef"])
    if (tags) {
      meta.takenAt = toCameraTime(tags.DateTimeOriginal) ?? toCameraTime(tags.CreateDate)
      const altitude = finiteOrNull(tags.GPSAltitude)
      // Phones write 0 when altitude is unknown; ref 1 means below sea level.
      if (altitude !== null && altitude > 0) {
        meta.altitude = Number(tags.GPSAltitudeRef) === 1 ? -altitude : altitude
      }
    }
  } catch {
    meta.takenAt = null
  }

  try {
    const gps = await exifr.gps(file)
    const latitude = finiteOrNull(gps?.latitude)
    const longitude = finiteOrNull(gps?.longitude)
    if (latitude !== null && longitude !== null && !(latitude === 0 && longitude === 0)) {
      meta.latitude = latitude
      meta.longitude = longitude
      meta.location = `纬度${latitude.toFixed(5)}，经度${longitude.toFixed(5)}`
    }
  } catch {
    meta.location = null
  }

  return meta
}
