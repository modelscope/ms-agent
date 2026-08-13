import { Image, Tooltip } from 'antd'
import type React from 'react'
import { useT } from '~/lib/i18n'

// File type icons. Inlined (`?react`) instead of loaded as <img> URLs so the
// theme-adaptive badges (e.g. web) can follow `currentColor` — an external SVG
// referenced by <img> has no inherited color and would render black.
import iconDefault from '~/assets/files/default.svg?react'
import iconPdf from '~/assets/files/pdf.svg?react'
import iconWord from '~/assets/files/word.svg?react'
import iconExcel from '~/assets/files/excel.svg?react'
import iconPpt from '~/assets/files/ppt.svg?react'
import iconZip from '~/assets/files/zip.svg?react'
import iconMarkdown from '~/assets/files/md.svg?react'
import iconJava from '~/assets/files/java.svg?react'
import iconJavascript from '~/assets/files/js.svg?react'
import iconPython from '~/assets/files/py.svg?react'
import iconText from '~/assets/files/txt.svg?react'
import iconMp3 from '~/assets/files/mp3.svg?react'
import iconWeb from '~/assets/files/web.svg?react'
import iconImage from '~/assets/icons/image.svg?react'
import iconAudio from '~/assets/icons/audio.svg?react'
import iconVideo from '~/assets/icons/video.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'
import RefreshIcon from '~/assets/icons/refresh.svg?react'
import SpinnerIcon from '~/assets/icons/generating.svg?react'

/** Upload lifecycle of an attached file. Selection triggers an immediate
 * upload to the project workspace; the composer blocks send until every file
 * is 'done' and drops 'error' ones. */
export type UploadStatus = 'uploading' | 'done' | 'error'

export interface AttachedFile {
  id: string
  file: File
  name: string
  byte: number
  type: 'file' | 'image' | 'audio' | 'video'
  src?: string
  /** Upload lifecycle; undefined is treated as 'done' (already-persisted). */
  status?: UploadStatus
  /** Workspace-relative path returned by the upload (e.g. user_files/foo.png). */
  path?: string
  /** Raw byte URL for preview / agent reference. */
  url?: string
}

export function fileToAttached(file: File): AttachedFile {
  const isImage = file.type.startsWith('image/')
  const isAudio = file.type.startsWith('audio/')
  const isVideo = file.type.startsWith('video/')
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    file,
    name: file.name,
    byte: file.size,
    type: isImage ? 'image' : isAudio ? 'audio' : isVideo ? 'video' : 'file',
    src: isImage || isAudio || isVideo ? URL.createObjectURL(file) : undefined,
    status: 'uploading'
  }
}

// ---- Utils ----

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)}MB`
}

function getFileExt(name: string): string {
  const parts = name.split('.')
  return parts.length > 1 ? parts.pop()!.toUpperCase() : 'FILE'
}

type FileIcon = React.FC<React.SVGProps<SVGSVGElement>>

// File extension to icon mapping
const fileIcons: Record<string, FileIcon> = {
  // Documents
  PDF: iconPdf,
  DOC: iconWord,
  DOCX: iconWord,
  // Spreadsheets
  XLS: iconExcel,
  XLSX: iconExcel,
  CSV: iconExcel,
  // Presentations
  PPT: iconPpt,
  PPTX: iconPpt,
  // Archives
  ZIP: iconZip,
  RAR: iconZip,
  '7Z': iconZip,
  TAR: iconZip,
  GZ: iconZip,
  // Code / Text
  MD: iconMarkdown,
  TXT: iconText,
  LOG: iconText,
  // Web sources
  HTML: iconWeb,
  HTM: iconWeb,
  CSS: iconWeb,
  // .ipynb has no dedicated badge asset; use the generic file badge so doc
  // cards render uniformly (matching the composer upload card) instead of the
  // odd line-art glyph.
  IPYNB: iconDefault,
  JS: iconJavascript,
  TS: iconJavascript,
  JSX: iconJavascript,
  TSX: iconJavascript,
  JAVA: iconJava,
  PY: iconPython,
  // Media
  PNG: iconImage,
  JPG: iconImage,
  JPEG: iconImage,
  GIF: iconImage,
  SVG: iconImage,
  WEBP: iconImage,
  MP3: iconMp3,
  WAV: iconAudio,
  OGG: iconAudio,
  FLAC: iconAudio,
  MP4: iconVideo,
  MOV: iconVideo,
  AVI: iconVideo,
  WEBM: iconVideo,
  MKV: iconVideo
}

function getFileIcon(ext: string): FileIcon {
  return fileIcons[ext] ?? iconDefault
}

/** File-type badge for a filename (extension-based, with fallback). The color
 * class only affects badges drawn with `currentColor` (the neutral ones); the
 * brand-colored plates carry their own fills. */
export function FileTypeIcon({
  name,
  className = ''
}: {
  name: string
  className?: string
}) {
  const Icon = getFileIcon(getFileExt(name))
  return <Icon aria-hidden className={`text-msa-icon-neutral ${className}`} />
}

/** Format a byte count into a compact human string (e.g. 1.25MB). */
export function formatFileSize(bytes: number): string {
  return formatSize(bytes)
}

// ---- Remove Button ----

function RemoveButton({ onClick }: { onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="absolute -right-1.5 -top-1.5 z-10 flex h-[20px] w-[20px] items-center justify-center rounded-full bg-red-500 text-[10px] text-white shadow-sm opacity-0 transition-opacity hover:bg-red-600 group-hover:opacity-100 border-none outline-none cursor-pointer"
    >
      {/* This icon library insets its glyphs to ~50% of the canvas, so the box
          must be the full badge size for the × to read at ~8px. */}
      <CloseIcon className="h-2.5 w-2.5" />
    </button>
  )
}

// Card chrome for media (image/audio/video) shown in the message list, so they
// match the document card. It's only applied when the card is NOT removable:
// composer upload previews (removable) render bare, without this outer frame.
// `group-hover/filecard:*` reacts to the clickable wrapper in a chat bubble
// (UserBubble) and tints the card on hover.
const MEDIA_CARD =
  'rounded-xl border border-msa-line-2 bg-msa-fill-0 transition-colors group-hover/filecard:bg-msa-fill-4'

// The native control (audio/video) and the antd image preview own their own
// clicks: stop the event so it doesn't bubble to the bubble wrapper's
// open-in-workspace handler. Clicking the surrounding card padding still opens.
const stopControl = {
  onClick: (e: React.MouseEvent) => e.stopPropagation(),
  onKeyDown: (e: React.KeyboardEvent) => e.stopPropagation()
}

// ---- Image Card ----

function ImageCard({
  src,
  name,
  removable,
  onRemove
}: {
  src?: string
  name: string
  removable?: boolean
  onRemove?: () => void
}) {
  const thumb = (
    <div className="h-20 w-20 overflow-hidden rounded-lg" {...stopControl}>
      <Image
        src={src}
        alt={name}
        width={80}
        height={80}
        classNames={{
          image: 'object-cover'
        }}
      />
    </div>
  )
  return (
    <div className="group relative">
      {removable && <RemoveButton onClick={onRemove} />}
      {removable ? (
        thumb
      ) : (
        <div className={`inline-block p-1.5 ${MEDIA_CARD}`}>{thumb}</div>
      )}
    </div>
  )
}

// ---- Audio Card ----

function AudioCard({
  src,
  removable,
  onRemove
}: {
  src?: string
  removable?: boolean
  onRemove?: () => void
}) {
  return (
    <div className="group relative">
      {removable && <RemoveButton onClick={onRemove} />}
      <div
        className={
          removable
            ? 'flex items-center'
            : `flex items-center p-2 ${MEDIA_CARD}`
        }
      >
        <audio src={src} controls className="w-[280px]" {...stopControl} />
      </div>
    </div>
  )
}

// ---- Video Card ----

function VideoCard({
  src,
  removable,
  onRemove
}: {
  src?: string
  removable?: boolean
  onRemove?: () => void
}) {
  return (
    <div className="group relative">
      {removable && <RemoveButton onClick={onRemove} />}
      <div
        className={
          removable ? 'inline-block' : `inline-block p-2 ${MEDIA_CARD}`
        }
      >
        <video
          src={src}
          controls
          className="block max-h-[200px] max-w-[200px] rounded-lg"
          {...stopControl}
        />
      </div>
    </div>
  )
}

// ---- Document File Card ----

function DocCard({
  name,
  byte,
  note,
  removable,
  onRemove
}: {
  name: string
  byte?: number
  /** Replaces the ext/size line with a note (e.g. "this file was deleted"). */
  note?: string
  removable?: boolean
  onRemove?: () => void
}) {
  const ext = getFileExt(name)

  return (
    <div className="group relative">
      {removable && <RemoveButton onClick={onRemove} />}
      <div className="flex min-w-[300px] items-center gap-3 rounded-xl border border-msa-line-2 bg-msa-fill-0 px-3 py-2.5 transition-colors group-hover/filecard:bg-msa-fill-4">
        <FileTypeIcon name={name} className="h-9 w-9 shrink-0" />
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm text-msa-text-1">{name}</span>
          {note ? (
            <span className="text-xs text-msa-text-danger mt-1">{note}</span>
          ) : (
            <span className="text-xs text-msa-text-3 mt-1">
              {ext}
              {byte != null && `  ${formatSize(byte)}`}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ---- Main FileCard ----

interface FileCardProps {
  name: string
  byte?: number
  type?: 'file' | 'image' | 'audio' | 'video'
  src?: string
  removable?: boolean
  onRemove?: () => void
  /** Upload lifecycle; when 'uploading'/'error' a status overlay is shown. */
  status?: UploadStatus
  /** Retry handler; wired to the error overlay so a failed upload can re-run. */
  onRetry?: () => void
  /** History replay: the workspace file is gone. Forces the generic doc card
   * (no media preview) and shows `note` in place of the ext/size line. */
  deleted?: boolean
  /** Sub-label under the name (e.g. the "file deleted" note). */
  note?: string
}

/** Overlay covering a card while an upload is in flight or after it failed. */
function StatusOverlay({
  status,
  onRetry
}: {
  status: UploadStatus
  onRetry?: () => void
}) {
  const { t } = useT()
  if (status === 'uploading') {
    return (
      <div className="absolute inset-0 z-20 flex items-center justify-center rounded-xl bg-msa-bg-1/60">
        <SpinnerIcon className="h-4 w-4 animate-spin text-msa-text-brand1" />
      </div>
    )
  }
  return (
    <Tooltip title={t.home.retryUpload}>
      <button
        type="button"
        onClick={onRetry}
        className="absolute inset-0 z-20 flex items-center justify-center gap-1 rounded-xl border border-msa-deco-red bg-msa-bg-1/70 text-xs text-msa-text-danger cursor-pointer outline-none"
      >
        <RefreshIcon className="h-3.5 w-3.5" />
      </button>
    </Tooltip>
  )
}

export function FileCard({
  name,
  byte,
  type = 'file',
  src,
  removable = false,
  onRemove,
  status,
  onRetry,
  deleted = false,
  note
}: FileCardProps) {
  const card = (() => {
    // A deleted file has no bytes to preview — always fall back to the generic
    // doc card, carrying the note (e.g. "this file was deleted").
    if (deleted) {
      return (
        <DocCard
          name={name}
          note={note}
          removable={removable}
          onRemove={onRemove}
        />
      )
    }
    switch (type) {
      case 'image':
        return (
          <ImageCard
            src={src}
            name={name}
            removable={removable}
            onRemove={onRemove}
          />
        )
      case 'audio':
        return <AudioCard src={src} removable={removable} onRemove={onRemove} />
      case 'video':
        return <VideoCard src={src} removable={removable} onRemove={onRemove} />
      default:
        return (
          <DocCard
            name={name}
            byte={byte}
            removable={removable}
            onRemove={onRemove}
          />
        )
    }
  })()

  if (!status || status === 'done') return card
  return (
    <div className="relative">
      {card}
      <StatusOverlay status={status} onRetry={onRetry} />
    </div>
  )
}
