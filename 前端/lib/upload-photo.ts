import { AppError } from "@/lib/errors"

// The upload endpoint rejects bodies above 15 MiB before server-side resizing.
// Keep headroom for server-side re-encoding and preserve a 2K-class source.
export const UPLOAD_LIMIT_BYTES = 15 * 1024 * 1024
const UPLOAD_TARGET_BYTES = 12 * 1024 * 1024
const UPLOAD_MAX_EDGE_PX = 2560

function encodeCanvas(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new AppError(1002, "图片压缩失败，请换一张照片重试"))
    }, type, quality)
  })
}

/** Resize only uploads that would hit the server's raw-body limit. */
export async function preparePhotoForUpload(file: File): Promise<File> {
  if (file.size <= UPLOAD_LIMIT_BYTES) return file

  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    throw new AppError(1002, "图片无法解码，请换一张照片重试")
  }

  try {
    const scale = Math.min(1, UPLOAD_MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement("canvas")
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
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
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)

    let output: Blob | null = null
    for (const quality of [0.94, 0.88, 0.8]) {
      output = await encodeCanvas(canvas, type, quality)
      if (output.type !== type) {
        type = "image/jpeg"
        context.fillStyle = "white"
        context.fillRect(0, 0, canvas.width, canvas.height)
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
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
    bitmap.close()
  }
}
