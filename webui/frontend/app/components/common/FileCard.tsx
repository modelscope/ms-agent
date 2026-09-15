import { Image, Tooltip } from 'antd'
import type React from 'react'
import { useT } from '~/lib/i18n'

// File type icons, inlined via `?react` so they render as sized SVG components.
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
import iconHtml from '~/assets/files/html.svg?react'
import iconCss from '~/assets/files/css.svg?react'
import iconSass from '~/assets/files/sass.svg?react'
import iconLess from '~/assets/files/less.svg?react'
import iconJson from '~/assets/files/json.svg?react'
import iconYaml from '~/assets/files/yaml.svg?react'
import iconXml from '~/assets/files/xml.svg?react'
import iconConfig from '~/assets/files/config.svg?react'
import iconDatabase from '~/assets/files/database.svg?react'
import iconShell from '~/assets/files/shell.svg?react'
import iconDocker from '~/assets/files/docker.svg?react'
import iconGit from '~/assets/files/git.svg?react'
import iconTs from '~/assets/files/ts.svg?react'
import iconGo from '~/assets/files/go.svg?react'
import iconRust from '~/assets/files/rust.svg?react'
import iconC from '~/assets/files/c.svg?react'
import iconCpp from '~/assets/files/cpp.svg?react'
import iconCsharp from '~/assets/files/csharp.svg?react'
import iconRuby from '~/assets/files/ruby.svg?react'
import iconPhp from '~/assets/files/php.svg?react'
import iconSwift from '~/assets/files/swift.svg?react'
import iconKotlin from '~/assets/files/kotlin.svg?react'
import iconVue from '~/assets/files/vue.svg?react'
import iconSvelte from '~/assets/files/svelte.svg?react'
import iconImage from '~/assets/icons/image.svg?react'
import iconAudio from '~/assets/icons/audio.svg?react'
import iconVideo from '~/assets/icons/video.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'
import JumpIcon from '~/assets/icons/jump.svg?react'
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

// Full filename (lowercased) to icon, checked before the extension map.
const fileNameIcons: Record<string, FileIcon> = {
  readme: iconMarkdown,
  'readme.md': iconMarkdown,
  'readme.txt': iconText,
  changelog: iconText,
  license: iconText,
  licence: iconText,
  copying: iconText,
  notice: iconText,
  authors: iconText,
  dockerfile: iconDocker,
  'docker-compose.yml': iconDocker,
  'docker-compose.yaml': iconDocker,
  '.dockerignore': iconDocker,
  '.gitignore': iconGit,
  '.gitattributes': iconGit,
  '.gitmodules': iconGit,
  '.gitkeep': iconGit,
  gemfile: iconRuby,
  'go.mod': iconGo,
  'go.sum': iconGo
}

// File extension to icon mapping
const fileIcons: Record<string, FileIcon> = {
  // Documents
  PDF: iconPdf,
  DOC: iconWord,
  DOCX: iconWord,
  RTF: iconWord,
  ODT: iconWord,
  // Spreadsheets
  XLS: iconExcel,
  XLSX: iconExcel,
  CSV: iconExcel,
  TSV: iconExcel,
  ODS: iconExcel,
  // Presentations
  PPT: iconPpt,
  PPTX: iconPpt,
  ODP: iconPpt,
  // Archives
  ZIP: iconZip,
  RAR: iconZip,
  '7Z': iconZip,
  TAR: iconZip,
  GZ: iconZip,
  TGZ: iconZip,
  BZ2: iconZip,
  XZ: iconZip,
  ZST: iconZip,
  JAR: iconZip,
  WAR: iconZip,
  // Code / Text
  MD: iconMarkdown,
  MDX: iconMarkdown,
  MARKDOWN: iconMarkdown,
  TXT: iconText,
  TEXT: iconText,
  LOG: iconText,
  NFO: iconText,
  IPYNB: iconDefault,
  // Data / config
  JSON: iconJson,
  JSONC: iconJson,
  JSON5: iconJson,
  YAML: iconYaml,
  YML: iconYaml,
  XML: iconXml,
  PLIST: iconXml,
  TOML: iconConfig,
  INI: iconConfig,
  CFG: iconConfig,
  CONF: iconConfig,
  ENV: iconConfig,
  PROPERTIES: iconConfig,
  EDITORCONFIG: iconConfig,
  // Database
  SQL: iconDatabase,
  DB: iconDatabase,
  SQLITE: iconDatabase,
  SQLITE3: iconDatabase,
  // Shell
  SH: iconShell,
  BASH: iconShell,
  ZSH: iconShell,
  FISH: iconShell,
  // Web sources
  HTML: iconHtml,
  HTM: iconHtml,
  XHTML: iconHtml,
  CSS: iconCss,
  STYL: iconCss,
  SCSS: iconSass,
  SASS: iconSass,
  LESS: iconLess,
  JS: iconJavascript,
  MJS: iconJavascript,
  CJS: iconJavascript,
  JSX: iconJavascript,
  TS: iconTs,
  TSX: iconTs,
  MTS: iconTs,
  CTS: iconTs,
  JAVA: iconJava,
  PY: iconPython,
  // Languages
  GO: iconGo,
  RS: iconRust,
  C: iconC,
  H: iconC,
  CPP: iconCpp,
  CC: iconCpp,
  CXX: iconCpp,
  HPP: iconCpp,
  HH: iconCpp,
  HXX: iconCpp,
  CS: iconCsharp,
  RB: iconRuby,
  PHP: iconPhp,
  SWIFT: iconSwift,
  KT: iconKotlin,
  KTS: iconKotlin,
  VUE: iconVue,
  SVELTE: iconSvelte,
  // Media
  PNG: iconImage,
  JPG: iconImage,
  JPEG: iconImage,
  GIF: iconImage,
  SVG: iconImage,
  WEBP: iconImage,
  ICO: iconImage,
  BMP: iconImage,
  TIFF: iconImage,
  TIF: iconImage,
  AVIF: iconImage,
  HEIC: iconImage,
  HEIF: iconImage,
  MP3: iconMp3,
  WAV: iconAudio,
  OGG: iconAudio,
  FLAC: iconAudio,
  M4A: iconAudio,
  AAC: iconAudio,
  OPUS: iconAudio,
  AIFF: iconAudio,
  WMA: iconAudio,
  MP4: iconVideo,
  MOV: iconVideo,
  AVI: iconVideo,
  WEBM: iconVideo,
  MKV: iconVideo,
  MPG: iconVideo,
  MPEG: iconVideo,
  M4V: iconVideo,
  FLV: iconVideo,
  WMV: iconVideo,
  '3GP': iconVideo,
  OGV: iconVideo
}

export function getFileIcon(name: string): FileIcon {
  const named = fileNameIcons[name.toLowerCase()]
  if (named) return named
  return fileIcons[getFileExt(name)] ?? iconDefault
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
  const Icon = getFileIcon(name)
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
      className="absolute -right-1.5 -top-1.5 z-10 flex h-[20px] w-[20px] items-center justify-center p-0 rounded-full bg-msa-fill-3  text-mas-text-0 shadow-sm  transition-opacity opacity-0 group-hover:opacity-100 border-none outline-none cursor-pointer"
    >
      <CloseIcon className="h-2.5 w-2.5" />
    </button>
  )
}

// Media in the message list renders BARE — no frame, no padding, no tinted
// surface. The picture/player is the content; wrapping it in card chrome added a
// rim that read as a gap and had nowhere useful to put a hover state. The
// "open in workspace" action lives in a corner button instead (see OpenButton),
// which is also the only way to offer it without the media element's own clicks
// (antd's preview, the native controls) fighting a whole-card handler.

// ---- Open-in-workspace Button ----

/** Hover-revealed corner action on a media card. Geometry is deliberately
 * identical to RemoveButton (same offsets, size and shape) — both are the same
 * class of corner affordance on the same cards, so they should land in exactly
 * the same spot. */
function OpenButton({ onClick }: { onClick?: () => void }) {
  const { t } = useT()
  return (
    <button
      type="button"
      title={t.session.openInWorkspace}
      onClick={(e) => {
        e.stopPropagation()
        onClick?.()
      }}
      className="absolute -right-1.5 -top-1.5 z-10 flex h-[20px] w-[20px] cursor-pointer items-center justify-center rounded-full border-none bg-msa-fill-3 p-0 text-msa-text-2 opacity-0 shadow-sm outline-none transition-opacity hover:text-msa-text-1 group-hover:opacity-100"
    >
      <JumpIcon className="h-5 w-5" />
    </button>
  )
}

// ---- Image Card ----

function ImageCard({
  src,
  removable,
  onRemove,
  onOpen
}: {
  src?: string
  removable?: boolean
  onRemove?: () => void
  onOpen?: () => void
}) {
  return (
    <div className="group relative">
      {removable && <RemoveButton onClick={onRemove} />}
      {!removable && onOpen && <OpenButton onClick={onOpen} />}
      <div className="h-20 w-20 overflow-hidden rounded-lg">
        {/* alt is empty on purpose: the thumbnail is decorative — the corner
            button is the labelled control, and a raw "image.png" here described
            nothing while being what a failed load would print on screen. */}
        <Image
          src={src}
          alt=""
          width={80}
          height={80}
          classNames={{
            image: 'object-cover'
          }}
        />
      </div>
    </div>
  )
}

// ---- Audio Card ----

function AudioCard({
  src,
  removable,
  onRemove,
  onOpen
}: {
  src?: string
  removable?: boolean
  onRemove?: () => void
  onOpen?: () => void
}) {
  return (
    <div className="group relative">
      {removable && <RemoveButton onClick={onRemove} />}
      {!removable && onOpen && <OpenButton onClick={onOpen} />}
      <div className="flex items-center">
        <audio src={src} controls className="w-[280px]" />
      </div>
    </div>
  )
}

// ---- Video Card ----

function VideoCard({
  src,
  removable,
  onRemove,
  onOpen
}: {
  src?: string
  removable?: boolean
  onRemove?: () => void
  onOpen?: () => void
}) {
  return (
    <div className="group relative inline-block">
      {removable && <RemoveButton onClick={onRemove} />}
      {!removable && onOpen && <OpenButton onClick={onOpen} />}
      <video
        src={src}
        controls
        className="block max-h-[200px] max-w-[200px] rounded-lg"
      />
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

  // `min-w-0` and the breakpoint on the floor are what keep this card inside a
  // phone. The name is `truncate` (so `white-space: nowrap`), which makes the
  // card's min-content width the *whole* filename — a 40-char one measures
  // 413px — and as a flex item with the default `min-width: auto` it refused to
  // shrink. Both rows it lives in overflowed: the message bubble's row is
  // `justify-end`, so the card ran off the LEFT edge (163px of a long filename
  // simply gone, and even a short name overhung by 50px), while the composer's
  // row pushed it off the right.
  //
  // The 300px floor is dropped only below `sm`, where the bubble row is ~250px
  // and no card can honour it; a phone gets a card that fits and an ellipsis.
  // From `sm` up the row is always well past 300px, so the floor — and the
  // uniform look it exists for — is untouched. Note a *percentage* floor
  // (`min(300px, 100%)`) does NOT work here: percentages count as zero during
  // intrinsic sizing, so it collapsed short cards to 142px at every width.
  return (
    <div className="group relative min-w-0">
      {removable && <RemoveButton onClick={onRemove} />}
      <div className="flex min-w-0 items-center gap-3 rounded-xl border border-msa-line-2 bg-msa-fill-0 px-3 py-2.5 transition-colors group-hover/filecard:bg-msa-fill-4 sm:min-w-[300px]">
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
  /** Media only: reveals a corner button that opens the file in the workspace.
   * Documents keep their whole-card click (wired by the caller) instead — a doc
   * card has no self-owned interaction to collide with. */
  onOpen?: () => void
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
  note,
  onOpen
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
            removable={removable}
            onRemove={onRemove}
            onOpen={onOpen}
          />
        )
      case 'audio':
        return (
          <AudioCard
            src={src}
            removable={removable}
            onRemove={onRemove}
            onOpen={onOpen}
          />
        )
      case 'video':
        return (
          <VideoCard
            src={src}
            removable={removable}
            onRemove={onRemove}
            onOpen={onOpen}
          />
        )
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
