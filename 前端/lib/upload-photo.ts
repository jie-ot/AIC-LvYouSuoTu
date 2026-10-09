import { AppError } from "@/lib/errors"

// The upload endpoint rejects bodies above 15 MiB before server-side resizing.
// Keep headroom for server-side re-encoding and preserve a 2K-class source.
export const UPLOAD_LIMIT_BYTES = 15 * 1024 * 1024
// Matches the backend's default upload pixel ceiling; byte size alone is
// insufficient for large panoramas saved with strong JPEG compression.
const UPLOAD_LIMIT_PIXELS = 40_000_000
const UPLOAD_TARGET_BYTES = 12 * 1024 * 1024
const UPLOAD_MAX_EDGE_PX = 2560
let decodingQueue = Promise.resolve()

interface DecodedPhoto {
  image: CanvasImageSource
  width: number
  height: number
  close: () => void
}

async function decodePhoto(file: File): Promise<DecodedPhoto> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(file)
    return { image: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() }
  }
  // Older WebViews can still upload ordinary photos and resize via canvas.
  const url = URL.createObjectURL(file)
  const image = new Image()
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error("Image decoding failed"))
      image.src = url
    })
    return { image, width: image.naturalWidth, height: image.naturalHeight,
      close: () => URL.revokeObjectURL(url) }
  } catch (error) {
    URL.revokeObjectURL(url)
    throw error
  }
}

function encodeCanvas(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new AppError(1002, "图片压缩失败，请换一张照片重试"))
    }, type, quality)
  })
}

/** Keep safe originals; resize files exceeding the server's byte or pixel limit. */
export async function preparePhotoForUpload(file: File): Promise<File> {
  // Bound peak decoded-image memory even when several upload workers encounter
  // high-pixel JPEGs whose compressed byte sizes are small.
  const previous = decodingQueue
  let release!: () => void
  decodingQueue = new Promise<void>((resolve) => { release = resolve })
  await previous
  let source: DecodedPhoto | undefined
  try {
    try {
      source = await decodePhoto(file)
    } catch {
      throw new AppError(1002, "图片无法解码，请换一张照片重试")
    }
    if (file.size <= UPLOAD_LIMIT_BYTES && source.width * source.height <= UPLOAD_LIMIT_PIXELS) return file

    const scale = Math.min(1, UPLOAD_MAX_EDGE_PX / Math.max(source.width, source.height))
    const canvas = document.createElement("canvas")
    canvas.width = Math.max(1, Math.round(source.width * scale))
    canvas.height = Math.max(1, Math.round(source.height * scale))
    const context = canvas.getContext("2d")
    if (!context) throw new AppError(1002, "图片压缩失败，请换一张照片重试")

    // WebP keeps PNG transparency. If the browser lacks WebP encoding,
    // flatten the image onto white before falling back to JPEG.
    const preferWebp = file.type === "image/png" || file.type === "image/webp"
    let type = preferWebp ? "image/webp" : "image/jpeg"
    if (type === "image/jpeg") {
      context.fillStyle = "white"
      context.fillRect(0, 0, canvas.width, canvas.height)
    }
    context.drawImage(source.image, 0, 0, canvas.width, canvas.height)

    let output: Blob | null = null
    for (const quality of [0.94, 0.88, 0.8]) {
      output = await encodeCanvas(canvas, type, quality)
      if (output.type !== type) {
        type = "image/jpeg"
        context.fillStyle = "white"
        context.fillRect(0, 0, canvas.width, canvas.height)
        context.drawImage(source.image, 0, 0, canvas.width, canvas.height)
        output = await encodeCanvas(canvas, type, quality)
      }
      if (output.size <= UPLOAD_TARGET_BYTES) break
    }
    if (!output || output.size > UPLOAD_TARGET_BYTES) {
      throw new AppError(1002, "图片压缩后仍过大，请换一张照片重试")
    }
    const extension = type === "image/webp" ? "webp" : "jpg"
    return new File([output], `${file.name.replace(/\.[^.]+$/, "")}.${extension}`, {
      type,
      lastModified: file.lastModified,
    })
  } finally {
    source?.close()
    release()
  }
}
