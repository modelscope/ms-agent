import { App, Button, Dropdown, Tooltip, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { taskStatusIcon } from '~/components/messages/TaskPlan'
import IconFolder from '~/assets/icons/folder.svg?react'
import IconTask from '~/assets/icons/task.svg?react'
import { NewProjectModal } from '~/components/project/NewProjectModal'
import { PillButton } from './PillButton'
import { api } from '~/lib/api'
import { useOnMcpSkillChanged, dispatchWorkspaceChanged } from '~/lib/events'
import type { ChatFileRef } from '~/lib/agentProvider'
import { useT } from '~/lib/i18n'
import type {
  AgentSettings,
  Mcp,
  Model,
  PermissionMode,
  Project,
  Provider,
  Scope,
  Skill
} from '~/lib/types'
import { FileCard, FileTypeIcon, fileToAttached } from './FileCard'
import type { AttachedFile } from './FileCard'
import { IconButton } from './IconButton'
import { StableSender } from './StableSender'
import type { SenderHandle } from './StableSender'
import type { SlotConfigType } from '@ant-design/x/es/sender'
import type { MessageSegment } from '~/lib/agentProvider'
import { ModelSelector } from './ModelSelector'
import { McpSelector } from './McpSelector'
import { SkillSelector } from './SkillSelector'
import './Composer.css'
import ExpandIcon from '~/assets/icons/expand.svg?react'
import CaretDownIcon from '~/assets/icons/chevron-down.svg?react'
import AddIcon from '~/assets/icons/add.svg?react'
import FolderIcon from '~/assets/icons/folder.svg?react'
import SendIcon from '~/assets/icons/send.svg?react'
import MoreIcon from '~/assets/icons/more.svg?react'

// Sender runs PERMANENTLY in slot mode (structured input): picked skills are
// inline tag pills among free text. Stable module-level empty config (the
// Sender rebuilds slot state on reference change) — slots are inserted
// imperatively via ref.insert().
const ALWAYS_SLOT_MODE: SlotConfigType[] = []

export interface ThinkingTask {
  id: string
  label: string
  status: 'done' | 'running' | 'pending' | 'waiting'
}

export interface ThinkingFile {
  id: string
  name: string
  type: 'file' | 'image' | 'video'
  /** Workspace-relative path — clicking the row opens it (via onOpenFile). */
  path?: string
  /** Written during the session but no longer on disk (shows a badge,
   * not clickable). */
  deleted?: boolean
}

export interface ThinkingState {
  tasks: ThinkingTask[]
  agentName?: string
  /** True only when the CURRENT turn's stream has reported plan activity —
   * gates the running spinner / "executing task" caption so a stale
   * plan-file "running" row doesn't animate during an unrelated turn. */
  planActive?: boolean
  files?: ThinkingFile[]
}

interface ComposerProps {
  onSubmit: (
    text: string,
    files?: ChatFileRef[],
    /** Ordered configuration-style segments (text + skill pills) exactly as
     * laid out in the input — present only when at least one pill was used. */
    segments?: MessageSegment[]
  ) => void
  loading?: boolean
  onCancel?: () => void
  /** Fired whenever the textarea value changes (used to snap the message list
   * to the bottom the moment the user starts typing). */
  onType?: () => void
  placeholder?: string
  autoSize?: { minRows?: number; maxRows?: number }
  project?: Project | null
  onProjectChange?: (projectId: string | null) => void
  attachable?: boolean

  /** Thinking state: shows gradient wrapper with task list */
  thinking?: ThinkingState | null
  /** Opens a session-produced file in the workspace rail (file list rows). */
  onOpenFile?: (path: string) => void
}

/** Skill-suggestion description: single-line, ellipsized when it overflows the
 * panel. When (and only when) it's actually clipped, hovering reveals the full
 * text in a tooltip. Truncation is measured on hover (cheap — one item at a
 * time), so no observers run for the whole list. */
function SuggestionDesc({ text }: { text: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [clipped, setClipped] = useState(false)
  return (
    <Tooltip title={clipped ? text : ''} placement="left">
      <span
        ref={ref}
        onMouseEnter={() => {
          const el = ref.current
          if (el) setClipped(el.scrollWidth > el.clientWidth)
        }}
        className="min-w-0 flex-1 truncate text-xs text-msa-text-3"
      >
        {text}
      </span>
    </Tooltip>
  )
}

export function Composer({
  onSubmit,
  loading = false,
  onCancel,
  onType,
  placeholder,
  autoSize: autoSizeProp,
  project,
  onProjectChange,
  attachable = true,
  thinking = null,
  onOpenFile
}: ComposerProps) {
  const autoSize = autoSizeProp ?? { minRows: 1, maxRows: 6 }
  const { t } = useT()
  const { message } = App.useApp()

  // Prevent SSR hydration flash: fix height until client mount
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    setMounted(true)
  }, [])

  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<AttachedFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Todo plan starts collapsed; the user expands it via the header chevron.
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  // The file list starts collapsed too — both sections open on demand only.
  const [filesExpanded, setFilesExpanded] = useState(false)
  // Drives the project-picker caret flip (antd Dropdown owns the panel).
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  // Project-level authorization mode selector (restricted / full access).
  const [permMenuOpen, setPermMenuOpen] = useState(false)
  // Optimistic override after a switch — reset when the project changes.
  const [permModeLocal, setPermModeLocal] = useState<PermissionMode | null>(
    null
  )
  // Small screen (<md): pills collapse behind a toggle. Visibility is CSS-driven
  // (md: classes) so the first paint is correct on any viewport with no
  // SSR/hydration flash; `pillsExpanded` only flips after a user click.
  const [pillsExpanded, setPillsExpanded] = useState(false)
  const pillsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!pillsExpanded) return
    const handleClickOutside = (e: MouseEvent) => {
      if (pillsRef.current && !pillsRef.current.contains(e.target as Node)) {
        setPillsExpanded(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [pillsExpanded])

  const [projects, setProjects] = useState<Project[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [pickedProjectId, setPickedProjectId] = useState<string | null>(null)

  // The project whose MCP/Skill/auto config applies: the route-level project,
  // or — on the homepage — the one chosen in the picker dropdown.
  const effectiveProject = useMemo(
    () => project ?? projects.find((p) => p.id === pickedProjectId) ?? null,
    [project, projects, pickedProjectId]
  )

  // null = not loaded yet, so the model pill's panel shows a skeleton instead
  // of "no models" before the lists arrive.
  const [models, setModels] = useState<Model[] | null>(null)
  const [providers, setProviders] = useState<Provider[] | null>(null)
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  // Fetch MCP/skill lists (global + project-scoped) directly. No shared
  // context — each Composer mount fetches fresh data for its project, merged.
  const [globalMcps, setGlobalMcps] = useState<Mcp[]>([])
  const [globalSkills, setGlobalSkills] = useState<Skill[]>([])
  const [projectMcps, setProjectMcps] = useState<Mcp[]>([])
  const [projectSkills, setProjectSkills] = useState<Skill[]>([])
  useEffect(() => {
    api
      .listMcps('global')
      .then(setGlobalMcps)
      .catch(() => setGlobalMcps([]))
    api
      .listSkills('global')
      .then(setGlobalSkills)
      .catch(() => setGlobalSkills([]))
    if (effectiveProject) {
      const scope: Scope = `project:${effectiveProject.id}`
      api
        .listMcps(scope)
        .then(setProjectMcps)
        .catch(() => setProjectMcps([]))
      api
        .listSkills(scope)
        .then(setProjectSkills)
        .catch(() => setProjectSkills([]))
    } else {
      setProjectMcps([])
      setProjectSkills([])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveProject?.id])

  // Re-fetch when MCP/Skill config changes on the same page (e.g. toggled in
  // the project-detail MCPs tab while Composer is mounted above).
  const refreshMcpSkill = useCallback(() => {
    api
      .listMcps('global')
      .then(setGlobalMcps)
      .catch(() => setGlobalMcps([]))
    api
      .listSkills('global')
      .then(setGlobalSkills)
      .catch(() => setGlobalSkills([]))
    if (effectiveProject) {
      const scope: Scope = `project:${effectiveProject.id}`
      api
        .listMcps(scope)
        .then(setProjectMcps)
        .catch(() => setProjectMcps([]))
      api
        .listSkills(scope)
        .then(setProjectSkills)
        .catch(() => setProjectSkills([]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveProject?.id])
  useOnMcpSkillChanged(refreshMcpSkill)

  const mergedMcps = useMemo(
    () => [...globalMcps, ...projectMcps],
    [globalMcps, projectMcps]
  )
  const mergedSkills = useMemo(
    () => [...globalSkills, ...projectSkills],
    [globalSkills, projectSkills]
  )

  const hasProjectPicker = !project && !!onProjectChange

  useEffect(() => {
    Promise.all([
      api.listProviders(),
      api.listModels(),
      api.getAgentSettings()
    ]).then(([ps, ms, s]) => {
      setProviders(ps)
      setModels(ms)
      setSettings(s)
    })
    if (hasProjectPicker) {
      api.listProjects().then(setProjects)
    }
  }, [hasProjectPicker])

  const updateSettings = async (patch: Partial<AgentSettings>) => {
    if (!settings) return
    const next = await api.putAgentSettings({ ...settings, ...patch })
    setSettings(next)
  }

  const skillSuggestions = useMemo(
    () =>
      mergedSkills
        .filter((s) => s.enabled)
        .map((s) => ({
          id: s.id,
          name: s.name,
          value: `/${s.name}`,
          label: `/${s.name}`,
          // One-liner description shown beside the name (same derivation as
          // SkillCard: first non-heading line of the skill content, which is
          // the SKILL.md description for discovered/built-in skills).
          desc:
            (s.content || '')
              .split('\n')
              .map((line) => line.trim())
              .find((line) => line && !line.startsWith('#')) ?? ''
        })),
    [mergedSkills]
  )

  // Skills the user picked from the slash dropdown, inserted into the
  // always-slot-mode Sender as inline tag pills. Repeatable: each pick gets a
  // UNIQUE slot key (same skill can appear multiple times, earlier pills are
  // never touched). Backspacing a pill away drops it from this list (synced
  // in onChange via the surviving slot keys).
  const [pickedSkills, setPickedSkills] = useState<
    { key: string; id: string; name: string }[]
  >([])
  const skillSeqRef = useRef(0)
  const senderRef = useRef<SenderHandle>(null)

  // ---- Slash-command suggestion panel ----
  const [suggestOpen, setSuggestOpen] = useState(false)
  const [suggestIndex, setSuggestIndex] = useState(0)
  const suggestOpenRef = useRef(false)

  const filteredSuggestions = useMemo(() => {
    if (!suggestOpen) return []
    const slashIdx = draft.lastIndexOf('/')
    if (slashIdx < 0) return skillSuggestions
    const query = draft.slice(slashIdx + 1).toLowerCase()
    return skillSuggestions.filter((s) => s.value.toLowerCase().includes(query))
  }, [suggestOpen, draft, skillSuggestions])

  const openSuggestions = useCallback(() => {
    setSuggestOpen(true)
    setSuggestIndex(0)
    suggestOpenRef.current = true
  }, [])

  const closeSuggestions = useCallback(() => {
    setSuggestOpen(false)
    suggestOpenRef.current = false
  }, [])

  const selectSuggestion = useCallback(
    (item: { id: string; name: string; value: string }) => {
      // Replace the trailing `/query` the user was typing with an inline tag
      // pill, in place (Sender is permanently in slot mode — no remount, the
      // rest of the draft is untouched). Each insertion gets a unique slot
      // key so repeated picks coexist instead of clobbering earlier pills.
      // `formatResult: ''` keeps the pill out of the plain-text value; ids
      // travel via `pickedSkills`.
      const slotKey = `skill-${item.id}-${skillSeqRef.current++}`
      const slashIdx = draft.lastIndexOf('/')
      const replaceChars = slashIdx >= 0 ? draft.slice(slashIdx) : ''
      senderRef.current?.insert(
        [
          {
            type: 'tag',
            key: slotKey,
            props: { label: item.value, value: item.id },
            formatResult: () => ''
          }
        ],
        'cursor',
        replaceChars || undefined
      )
      setPickedSkills((prev) => [
        ...prev,
        { key: slotKey, id: item.id, name: item.name }
      ])
      closeSuggestions()
    },
    [draft, closeSuggestions]
  )

  const handleSuggestionKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!suggestOpenRef.current || filteredSuggestions.length === 0) return
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSuggestIndex((i) => (i + 1) % filteredSuggestions.length)
          break
        case 'ArrowUp':
          e.preventDefault()
          setSuggestIndex(
            (i) =>
              (i - 1 + filteredSuggestions.length) % filteredSuggestions.length
          )
          break
        case 'Enter':
          e.preventDefault()
          e.stopPropagation()
          selectSuggestion(filteredSuggestions[suggestIndex])
          break
        case 'Escape':
          e.preventDefault()
          closeSuggestions()
          break
      }
    },
    [filteredSuggestions, suggestIndex, selectSuggestion, closeSuggestions]
  )

  const defaultProject = useMemo(
    () => projects.find((p) => p.is_default) ?? null,
    [projects]
  )

  // Default the picker to the default project when nothing is picked yet.
  useEffect(() => {
    if (hasProjectPicker && defaultProject && pickedProjectId === null) {
      setPickedProjectId(defaultProject.id)
      onProjectChange?.(defaultProject.id)
    }
  }, [hasProjectPicker, defaultProject, pickedProjectId, onProjectChange])

  // The project files land in: fixed project, or the picked one on the homepage
  // new-chat (defaulted to the default project by the effect above).
  const effectiveProjectId = project?.id ?? pickedProjectId

  // Authorization mode of the effective project (optimistic local override
  // wins until the project changes). Persisted project-side; live runtimes are
  // hot-switched by the backend, so it applies to the current turn's next call.
  const permMode: PermissionMode =
    permModeLocal ?? effectiveProject?.permission_mode ?? 'restricted'

  useEffect(() => {
    setPermModeLocal(null)
  }, [effectiveProjectId])

  const switchPermMode = async (mode: PermissionMode) => {
    if (!effectiveProjectId || mode === permMode) return
    setPermModeLocal(mode)
    try {
      await api.updateProject(effectiveProjectId, { permission_mode: mode })
    } catch {
      setPermModeLocal(null) // global error toast handles the message
    }
  }

  const MAX_FILES = 10

  // Upload one attached file to <project>/user_files/ immediately on selection,
  // then stamp the real (deduped) path + raw URL the backend returns. Failures
  // flip the card to an 'error' state that the user can retry.
  const uploadOne = useCallback(
    async (att: AttachedFile) => {
      if (!effectiveProjectId) {
        setFiles((prev) =>
          prev.map((f) => (f.id === att.id ? { ...f, status: 'error' } : f))
        )
        return
      }
      setFiles((prev) =>
        prev.map((f) => (f.id === att.id ? { ...f, status: 'uploading' } : f))
      )
      try {
        const res = await api.uploadWorkspaceFile(
          effectiveProjectId,
          att.file,
          `user_files/${att.file.name}`,
          { dedup: true }
        )
        const url = api.workspaceFileRawUrl(effectiveProjectId, res.path)
        setFiles((prev) =>
          prev.map((f) =>
            f.id === att.id ? { ...f, status: 'done', path: res.path, url } : f
          )
        )
        // The upload landed a new file in the workspace (user_files/…) — tell
        // the workspace panel / file tree so it shows up without a manual
        // refresh. Pass the real deduped path as an optimistic "exists" hint.
        dispatchWorkspaceChanged([res.path])
      } catch {
        setFiles((prev) =>
          prev.map((f) => (f.id === att.id ? { ...f, status: 'error' } : f))
        )
      }
    },
    [effectiveProjectId]
  )

  const hasUploading = files.some((f) => f.status === 'uploading')
  const hasReadyFiles = files.some((f) => f.status === 'done')
  // Send is allowed when nothing is still uploading and there is text, a
  // ready file, or a picked skill pill (a bare skill invocation is valid —
  // the backend answers with the skill intro).
  const canSend =
    !hasUploading &&
    (!!draft.trim() || hasReadyFiles || pickedSkills.length > 0)

  const handleSubmit = (value: string) => {
    const text = value.trim()
    if (hasUploading) return
    const ready = files.filter((f) => f.status === 'done' && f.path)
    if (!text && ready.length === 0 && pickedSkills.length === 0) return
    const refs: ChatFileRef[] = ready.map((f) => ({
      name: f.name,
      path: f.path!,
      url: f.url,
      size: f.byte,
      type: f.type
    }))
    // Rebuild the ORDERED segments from the editable area's document-order
    // slot structure (free text nodes interleaved with skill pills) — the
    // flat (text, ids) pair would lose the interleaving.
    const slotCfg = senderRef.current?.getValue()?.slotConfig ?? []
    const segments: MessageSegment[] = []
    for (const node of slotCfg) {
      if (node.type === 'text') {
        const t = String((node as { value?: unknown }).value ?? '').trim()
        if (t) segments.push({ type: 'text', text: t })
      } else if (node.type === 'tag') {
        const pick = pickedSkills.find((p) => p.key === node.key)
        if (pick) segments.push({ type: 'skill', id: pick.id, name: pick.name })
      }
    }
    const hasSkill = segments.some((s) => s.type === 'skill')
    onSubmit(text, refs, hasSkill ? segments : undefined)
    setDraft('')
    setFiles([])
    setPickedSkills([])
    // Slot mode is uncontrolled; clear the editable area imperatively.
    senderRef.current?.clear()
  }

  /** Queue files as attachments and start their uploads. Shared by the picker
   * button, and by pasting (screenshots / files from the OS clipboard) — both
   * must honour the same MAX_FILES cap and upload-on-select behaviour. The cap
   * toast only ever fires for paste: the picker button is disabled at the cap,
   * so a silent no-op there would be invisible. */
  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const list = Array.from(incoming)
      if (list.length === 0) return
      const remaining = MAX_FILES - files.length
      if (remaining <= 0) {
        message.warning(t.home.maxFilesReached)
        return
      }
      const added = list.slice(0, remaining).map(fileToAttached)
      setFiles((prev) => [...prev, ...added])
      // Upload each immediately so the real link exists before send.
      added.forEach((att) => void uploadOne(att))
    },
    [files.length, uploadOne, message, t]
  )

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(e.target.files)
    e.target.value = ''
  }

  const isMaxFiles = files.length >= MAX_FILES

  const removeFile = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id))
  }

  const projectMenuItems: MenuProps['items'] = hasProjectPicker
    ? [
        ...(defaultProject
          ? [
              {
                key: defaultProject.id,
                icon: <FolderIcon className="h-4 w-4" />,
                label: defaultProject.name,
                onClick: () => {
                  setPickedProjectId(defaultProject.id)
                  onProjectChange?.(defaultProject.id)
                }
              },
              { type: 'divider' as const }
            ]
          : []),
        ...projects
          .filter((p) => !p.is_default)
          .map((p) => ({
            key: p.id,
            icon: <FolderIcon className="h-4 w-4" />,
            label: p.name,
            onClick: () => {
              setPickedProjectId(p.id)
              onProjectChange?.(p.id)
            }
          })),
        { type: 'divider' as const },
        {
          key: '__create__',
          icon: <AddIcon className="h-4 w-4" />,
          label: t.home.createProject,
          onClick: () => setCreateOpen(true)
        }
      ]
    : undefined

  // Shared design-spec status glyphs (single source in TaskPlan). `loading`
  // gates the running spinner — a "running" item with no live turn is stale
  // plan-file state and degrades to the paused glyph.

  const doneCount =
    thinking?.tasks.filter((t) => t.status === 'done').length ?? 0
  const totalCount = thinking?.tasks.length ?? 0
  // "Running" is only trusted while THIS turn actually reported plan
  // activity: the plan file keeps its last "in_progress" row across turns
  // (interrupted or unrelated ones), and animating it on every send reads as
  // phantom activity.
  const planLive = loading && (thinking?.planActive ?? false)
  const runningTask = planLive
    ? thinking?.tasks.find((t) => t.status === 'running')
    : undefined

  return (
    <>
      {/* Outer wrapper: gradient when thinking, plain otherwise.
          Non-thinking keeps 3px padding so the card's focus glow (::before at
          inset:-3px) stays inside this box and never bleeds out to trigger a
          scrollbar on an ancestor scroll container. */}
      <div
        className={`relative flex flex-col rounded-3xl ${
          thinking ? 'composer-thinking-wrapper p-5 gap-3' : 'p-[3px]'
        }`}
      >
        {/* Ambient motion while a task is ACTUALLY running this turn (same
            planActive gate as the spinner). Fades in/out via opacity transition
            so it never "pops" on/off. */}
        {thinking && (
          <div
            className={`composer-motion-layer transition-opacity duration-700 ease-in-out ${
              planLive ? 'opacity-100' : 'opacity-0 pointer-events-none'
            }`}
            aria-hidden
          >
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
        )}
        {/* Thinking header + task list. The plan now renders inline in the
            conversation (TaskPlan) in stream order, so it is no longer pinned
            here — this only shows if a plan is explicitly present. Each
            section wraps header+body in ONE flex child so a collapsed body
            doesn't eat an extra gap slot (the design's tight spacing). */}
        {thinking && thinking.tasks.length > 0 && (
          <div className="flex flex-col">
            <div className="flex items-center justify-between gap-2">
              {/* The whole text block toggles the accordion, not just the
                  chevron. */}
              <button
                type="button"
                onClick={() => setThinkingExpanded((v) => !v)}
                className="flex shrink-0 cursor-pointer items-center gap-1 border-none bg-transparent p-0 text-left outline-none"
              >
                <IconTask className="h-5 w-5" />
                <span className="text-sm font-medium text-msa-text-1">
                  {t.home.thinkingTasks}
                </span>
                <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-xs text-msa-text-3">
                  {doneCount}/{totalCount}
                </span>
                <ExpandIcon
                  className={`ml-1 h-5 w-5 text-msa-text-3 transition-transform ${
                    thinkingExpanded ? '' : 'rotate-180'
                  }`}
                />
              </button>
              <div className="flex-1 w-0 flex justify-end">
                {runningTask && (
                  <Typography.Text
                    ellipsis={{
                      tooltip: `${t.home.runningTask}${runningTask.label}`
                    }}
                    className="min-w-0 text-msa-text-3"
                  >
                    <span className="text-xs">
                      {t.home.runningTask}
                      {runningTask.label}
                    </span>
                  </Typography.Text>
                )}
              </div>
            </div>

            <div
              className={`grid transition-[grid-template-rows] duration-200 ease-out ${thinkingExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
            >
              <div className="overflow-hidden">
                {/* Expanded task list sits in its own bordered container
                    (design spec: fill-1 bg, line-1 border, 24px radius). */}
                <div className="mt-2 rounded-3xl border border-msa-line-1 bg-msa-fill-1 px-[16px] py-[11px] overflow-y-auto max-h-[20vh]">
                  <div className="flex max-h-[30vh] flex-col overflow-y-auto">
                    {thinking.tasks.map((task, i) => (
                      <div key={task.id} className="flex gap-2 text-sm">
                        {/* Status circle + dashed connector to the next item
                          (same timeline styling as the in-chat TaskPlan). */}
                        <div className="flex flex-col items-center self-stretch">
                          {/* overflow-hidden: the spinning icon's rotated
                              bounding box would otherwise extend the scroll
                              area and summon a scrollbar. */}
                          <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden">
                            {taskStatusIcon(task.status, planLive)}
                          </span>
                          {i < thinking.tasks.length - 1 && (
                            <span className="w-[0px] flex-1 border-0 border-l border-dashed border-[#D8D8D8]" />
                          )}
                        </div>
                        <span
                          className={`min-w-0 flex-1 ${
                            i < thinking.tasks.length - 1 ? 'pb-3' : ''
                          } ${
                            task.status === 'done'
                              ? 'text-msa-text-1'
                              : task.status === 'running'
                                ? 'text-msa-text-1'
                                : 'text-msa-text-3'
                          }`}
                        >
                          {task.label}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* File list (optional, inside thinking wrapper) */}
        {thinking?.files && thinking.files.length > 0 && (
          <div className="flex flex-col">
            {/* The whole text block toggles the accordion, not just the
                chevron. */}
            <button
              type="button"
              onClick={() => setFilesExpanded((v) => !v)}
              className="flex w-fit cursor-pointer items-center gap-1 border-none bg-transparent p-0 text-left outline-none"
            >
              <IconFolder className="h-5 w-5" />
              <span className="ml-1 text-sm font-medium text-msa-text-1">
                {t.home.thinkingFiles}
              </span>
              <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-xs text-msa-text-3">
                {thinking.files.length}
              </span>
              <ExpandIcon
                className={`ml-1 h-5 w-5 text-msa-text-3 transition-transform ${
                  filesExpanded ? '' : 'rotate-180'
                }`}
              />
            </button>
            <div
              className={`grid transition-[grid-template-rows] duration-200 ease-out ${filesExpanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
            >
              <div className="overflow-hidden">
                <div className="flex max-h-[15vh] flex-col gap-2.5 overflow-y-auto pl-1 pt-2">
                  {thinking.files.map((f) => {
                    const clickable = !f.deleted && !!f.path && !!onOpenFile
                    return (
                      <div
                        key={f.id}
                        className={`flex items-center gap-2 text-sm ${
                          f.deleted
                            ? 'text-msa-text-3'
                            : clickable
                              ? 'cursor-pointer text-msa-text-1 hover:text-msa-text-brand1'
                              : 'text-msa-text-1'
                        }`}
                        onClick={
                          clickable ? () => onOpenFile?.(f.path!) : undefined
                        }
                      >
                        <FileTypeIcon
                          name={f.name}
                          className={`h-4 w-4 ${f.deleted ? 'opacity-50' : ''}`}
                        />
                        <span
                          className={`min-w-0 truncate ${
                            f.deleted ? 'line-through' : ''
                          }`}
                        >
                          {f.name}
                        </span>
                        {f.deleted && (
                          <span className="shrink-0 text-xs text-msa-text-3">
                            {t.home.fileDeleted}
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Card-style composer container */}
        <div className="composer-card relative flex flex-col rounded-2xl border border-msa-line-1 bg-msa-bg-1 p-5 shadow-msa-m">
          {/* Project picker (top-right, outside card flow) */}
          {hasProjectPicker && projectMenuItems && (
            <div className="absolute -top-8 right-0">
              <Dropdown
                menu={{ items: projectMenuItems }}
                trigger={['click']}
                onOpenChange={setProjectMenuOpen}
              >
                <Button
                  size="small"
                  type="text"
                  className="!text-xs !text-msa-text-3"
                >
                  {effectiveProject
                    ? effectiveProject.name
                    : (defaultProject?.name ?? t.home.noProject)}
                  <CaretDownIcon
                    className={`ml-1 h-[7px] w-[7px] transition-transform duration-200 ${
                      projectMenuOpen ? 'rotate-180' : ''
                    }`}
                  />
                </Button>
              </Dropdown>
            </div>
          )}

          {/* Sender (textarea) with slash-command suggestion */}
          {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
          <div onKeyDown={handleSuggestionKeyDown}>
            <Dropdown
              open={suggestOpen && filteredSuggestions.length > 0}
              placement="top"
              autoAdjustOverflow={false}
              popupRender={() => (
                <div className="max-h-52 w-fit max-w-[min(420px,80cqw)] overflow-y-auto rounded-2xl border border-msa-line-1 bg-msa-bg-1 p-2 shadow-msa-m">
                  {filteredSuggestions.map((item, idx) => (
                    <div
                      key={item.value}
                      className={`flex cursor-pointer items-baseline gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                        idx === suggestIndex
                          ? 'bg-msa-fill-4 text-msa-text-brand1'
                          : 'text-msa-text-1 hover:bg-msa-fill-4 hover:text-msa-text-brand1'
                      }`}
                      onMouseEnter={() => setSuggestIndex(idx)}
                      onMouseDown={(e) => {
                        e.preventDefault()
                        selectSuggestion(item)
                      }}
                    >
                      <span className="shrink-0 font-medium">{item.label}</span>
                      {item.desc && <SuggestionDesc text={item.desc} />}
                    </div>
                  ))}
                </div>
              )}
            >
              <div>
                <StableSender
                  ref={senderRef}
                  slotConfig={ALWAYS_SLOT_MODE}
                  onChange={(v, _e, slotCfg) => {
                    setDraft(v)
                    // Backspacing a pill away cancels that pick — keep only
                    // entries whose slot key survived in the editable area.
                    setPickedSkills((prev) => {
                      if (prev.length === 0) return prev
                      const alive = new Set(
                        (slotCfg ?? [])
                          .filter((s) => s.type === 'tag')
                          .map((s) => s.key)
                      )
                      const next = prev.filter((p) => alive.has(p.key))
                      return next.length === prev.length ? prev : next
                    })
                    onType?.()
                    if (v === '/' || v.endsWith(' /')) {
                      openSuggestions()
                    } else if (!v.includes('/')) {
                      closeSuggestions()
                    }
                  }}
                  onSubmit={handleSubmit}
                  // Pasted screenshots / OS-clipboard files become attachments,
                  // same pipeline as the picker button. (Rich text needs no
                  // handling: Sender's slot-mode paste already inserts only
                  // text/plain, so styles never enter the editable area.)
                  onPasteFile={addFiles}
                  onKeyDown={(e) => {
                    // Suggestion open: let Enter pick a suggestion instead.
                    if (
                      suggestOpenRef.current &&
                      filteredSuggestions.length > 0
                    )
                      return
                    // Skip while IME composing.
                    if (e.nativeEvent.isComposing) return
                    if (
                      e.key === 'Enter' &&
                      !e.shiftKey &&
                      !e.metaKey &&
                      !e.ctrlKey &&
                      !e.altKey
                    ) {
                      e.preventDefault()
                      // While a reply is streaming, Enter must not send new
                      // content; the user has to stop first.
                      if (loading) return false
                      handleSubmit(draft)
                      return false
                    }
                  }}
                  onCancel={onCancel}
                  loading={loading}
                  placeholder={placeholder ?? t.home.placeholder}
                  autoSize={autoSize}
                  suffix={false}
                  className="!border-none !bg-transparent !shadow-none !p-0"
                  styles={{
                    input: !mounted
                      ? {
                          height: (autoSize.minRows || 1) * 14
                        }
                      : undefined
                  }}
                  classNames={{
                    input: '!bg-transparent outline-none',
                    content: '!p-0',
                    footer: '!p-0'
                  }}
                  header={
                    files.length > 0 ? (
                      <div className="flex flex-wrap gap-2 pb-3">
                        {files.map((f) => (
                          <FileCard
                            key={f.id}
                            name={f.name}
                            byte={f.byte}
                            type={f.type}
                            src={f.src}
                            status={f.status}
                            onRetry={() => void uploadOne(f)}
                            removable
                            onRemove={() => removeFile(f.id)}
                          />
                        ))}
                      </div>
                    ) : undefined
                  }
                  footer={
                    // @container: makes this footer an inline-size query
                    // container so the pills can cap their width relative to the
                    // composer column (cqw), not the viewport — the composer can
                    // be narrow while the viewport stays wide (e.g. a detail rail
                    // is open), so a viewport-relative cap would overflow.
                    <div className="@container relative flex items-center justify-between gap-2 pt-3">
                      {/* Left: pills. Collapsed behind a toggle on <md, inline on
                          >=md. Visibility is CSS-driven (md: classes) so the first
                          paint is correct with no SSR/hydration flash. When expanded
                          on small screens the group floats above the row. */}
                      <div
                        ref={pillsRef}
                        className={`flex flex-wrap items-center gap-2.5 ${
                          pillsExpanded
                            ? 'absolute left-0 bottom-0 z-10 bg-msa-bg-1 pt-3 md:static md:bg-transparent md:pt-0'
                            : ''
                        }`}
                      >
                        {/* Toggle button: shown only on <md while collapsed */}
                        {!pillsExpanded && (
                          <IconButton
                            className="md:hidden"
                            icon={<MoreIcon className="h-4 w-4" />}
                            onClick={() => setPillsExpanded(true)}
                          />
                        )}

                        {/* Pills: hidden on <md unless expanded; always inline on >=md */}
                        <div
                          className={`flex flex-wrap items-center gap-2.5 ${
                            pillsExpanded ? '' : 'hidden md:flex'
                          }`}
                        >
                          {/* Model pill */}
                          <ModelSelector
                            models={models}
                            providers={providers}
                            settings={settings}
                            onSelectModel={(providerId, modelId) =>
                              updateSettings({
                                default_provider_id: providerId,
                                default_model_id: modelId
                              })
                            }
                          />

                          {/* MCP pill */}
                          <McpSelector
                            items={mergedMcps}
                            // Any selected project counts — including the home
                            // page's project picker — so the settings link
                            // targets that project's MCP tab.
                            project={effectiveProject}
                          />

                          {/* Skills pill */}
                          <SkillSelector
                            items={mergedSkills}
                            project={effectiveProject}
                          />

                          {/* Project-level authorization mode — same pill as
                              the model/MCP/skill selectors. Label IS the mode;
                              switching persists to the project and hot-applies
                              to live runtimes. */}
                          <Dropdown
                            trigger={['click']}
                            onOpenChange={setPermMenuOpen}
                            menu={{
                              selectedKeys: [permMode],
                              items: [
                                {
                                  key: 'restricted',
                                  label: t.home.permAlwaysAsk,
                                  onClick: () => switchPermMode('restricted')
                                },
                                {
                                  key: 'auto',
                                  label: t.home.permFullAccess,
                                  onClick: () => switchPermMode('auto')
                                }
                              ]
                            }}
                          >
                            <PillButton open={permMenuOpen}>
                              {permMode === 'auto'
                                ? t.home.permFullAccess
                                : t.home.permAlwaysAsk}
                            </PillButton>
                          </Dropdown>
                        </div>
                      </div>

                      {/* Right: attach + send */}
                      <div className="flex items-center gap-2">
                        {attachable && (
                          <>
                            <input
                              ref={fileInputRef}
                              type="file"
                              multiple
                              className="hidden"
                              onChange={handleFileChange}
                            />
                            <Tooltip
                              title={
                                isMaxFiles
                                  ? t.home.maxFilesReached
                                  : t.home.addFile
                              }
                            >
                              <IconButton
                                icon={<AddIcon className="h-4 w-4" />}
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isMaxFiles}
                              />
                            </Tooltip>
                          </>
                        )}
                        <Tooltip title={loading ? t.home.stop : t.home.send}>
                          {loading ? (
                            <IconButton
                              variant="primary"
                              icon={
                                <span className="block h-2.5 w-2.5 rounded-[2px] bg-current" />
                              }
                              onClick={() => onCancel?.()}
                            />
                          ) : (
                            <IconButton
                              variant="primary"
                              icon={<SendIcon className="h-4 w-4" />}
                              onClick={() => handleSubmit(draft)}
                              disabled={!canSend}
                            />
                          )}
                        </Tooltip>
                      </div>
                    </div>
                  }
                />
              </div>
            </Dropdown>
          </div>
        </div>
      </div>

      {hasProjectPicker && (
        <NewProjectModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={(p) => {
            setCreateOpen(false)
            setProjects((prev) => [...prev, p])
            setPickedProjectId(p.id)
            onProjectChange?.(p.id)
          }}
        />
      )}
    </>
  )
}
