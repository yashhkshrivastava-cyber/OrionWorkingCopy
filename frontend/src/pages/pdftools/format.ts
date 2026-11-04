/** A size in bytes the way people say it: 840 KB, 3.2 MB. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`

const IMAGE_EXTENSIONS = /\.(jpe?g|png|webp|gif|bmp|tiff?|heic|heif)$/i

export const isPdfFile = (file: File) => file.type === 'application/pdf' || /\.pdf$/i.test(file.name)

export const isImageFile = (file: File) => file.type.startsWith('image/') || IMAGE_EXTENSIONS.test(file.name)
