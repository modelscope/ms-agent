/**
 * Which media element plays a file, by extension alone.
 *
 * Extension rather than the server's MIME type, so renaming a file changes its
 * preview at once, and so markdown can decide before anything is fetched.
 */

export type MediaKind = 'image' | 'video' | 'audio'

const IMAGE_EXTS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'svg',
  'bmp',
  'ico',
  'avif'
])
const VIDEO_EXTS = new Set(['mp4', 'webm', 'ogg', 'mov', 'avi', 'mkv'])
const AUDIO_EXTS = new Set(['mp3', 'wav', 'aac', 'flac', 'm4a', 'wma', 'opus'])

/**
 * Extension of a path's basename, lowercased; '' when it has none.
 *
 * Only a real extension counts: text after the last dot of the BASENAME, and
 * only when that dot isn't the leading character. `logging` / `Dockerfile` (no
 * dot) and `.locks` (dotfile) have NO extension — a naive `split('.').pop()`
 * would return the whole name instead.
 */
export function extensionOf(path: string): string {
  const name = path.split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

/** The media element a file plays in, or null when it isn't media. */
export function mediaKindFor(path: string): MediaKind | null {
  const ext = extensionOf(path)
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (VIDEO_EXTS.has(ext)) return 'video'
  if (AUDIO_EXTS.has(ext)) return 'audio'
  return null
}
