import { App, Button, Dropdown, Tooltip, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useRevalidator, useRouteLoaderData } from 'react-router'
import type { loader as appLoader } from '~/layouts/app'
import { taskStatusIcon } from '~/components/messages/TaskPlan'
import IconFolder from '~/assets/icons/folder.svg?react'
import IconTask from '~/assets/icons/task.svg?react'
import { NewProjectModal } from '~/components/project/NewProjectModal'
import { PillButton } from './PillButton'
import { api } from '~/lib/api'
import { useSessionModel, type SessionModelSelection } from '~/lib/sessionModel'
import { useModelChanged } from '~/lib/modelChanged'
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
  SearchSettings,
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
import EditIcon from '~/assets/icons/edit.svg?react'

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
  modelSelection?: SessionModelSelection
  modelSelectionDisabled?: boolean
  onSubmit: (
    text: string,
    files?: ChatFileRef[],
    /** Ordered configuration-style segments (text + skill pills) exactly as
     * laid out in the input — present only when at least one pill was used. */
    segments?: MessageSegment[],
    modelId?: string
  ) => void | Promise<void>
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
  modelSelection: providedSelection,
  modelSelectionDisabled = false,
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
  const navigate = useNavigate()
  const revalidator = useRevalidator()

  // Projects/models/providers/settings and the global MCP + Skill lists are
  // resolved by the app layout's loader, so they are available before the first
  // render instead of arriving mid-flight and resizing the pill row.
  const appData = useRouteLoaderData('layouts/app') as
    | Awaited<ReturnType<typeof appLoader>>
    | undefined
  const hasAppData = !!appData

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
  // Narrow composer: pills collapse behind a toggle. Visibility is CSS-driven
  // (container queries on the footer) so the first paint is correct at any width
  // with no SSR/hydration flash; `pillsExpanded` only flips after a user click.
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

  const [projects, setProjects] = useState<Project[]>(appData?.projects ?? [])
  const [createOpen, setCreateOpen] = useState(false)
  const [pickedProjectId, setPickedProjectId] = useState<string | null>(null)

  const hasProjectPicker = !project && !!onProjectChange

  const defaultProject = useMemo(
    () => projects.find((p) => p.is_default) ?? null,
    [projects]
  )

  // The project whose MCP/Skill/auto config applies: the route-level project,
  // or — on the homepage — the one chosen in the picker dropdown. The last
  // branch resolves the picker's default in the SAME render that the effect
  // below only commits one frame later: sending the first message remounts this
  // component, and a project-less first paint would show the pills' fallbacks
  // (notably "always ask") instead of what the turn actually runs with.
  const effectiveProject = useMemo(
    () =>
      project ??
      projects.find((p) => p.id === pickedProjectId) ??
      (hasProjectPicker ? defaultProject : null),
    [project, projects, pickedProjectId, hasProjectPicker, defaultProject]
  )

  // Toolbar data comes from the app layout's loader, so the pills render their
  // real labels in the very first paint. Seeding state (rather than reading the
  // loader on every render) keeps the optimistic updates below working: a model
  // switch shows immediately without waiting for a revalidation.
  const [models, setModels] = useState<Model[] | null>(appData?.models ?? null)
  const [providers, setProviders] = useState<Provider[] | null>(
    appData?.providers ?? null
  )
  const [globalSettings, setSettings] = useState<AgentSettings | null>(
    appData?.agentSettings ?? null
  )
  const draftSelection = useSessionModel(
    null,
    appData?.agentSettings.default_model_id ?? '',
    !providedSelection
  )
  const modelSelection = providedSelection ?? draftSelection
  const selectedProvider =
    models?.find((m) => m.id === modelSelection.modelId)?.provider_id ?? null
  const settings = globalSettings
    ? {
        ...globalSettings,
        default_model_id: modelSelection.modelId,
        default_provider_id: selectedProvider
      }
    : null
  const submitting = useRef(false)
  const [preparing, setPreparing] = useState(false)
  // Global lists also come from the loader; only the project-scoped halves are
  // fetched here, since the project can be picked in this component (homepage).
  const [globalMcps, setGlobalMcps] = useState<Mcp[]>(appData?.globalMcps ?? [])
  const [globalSkills, setGlobalSkills] = useState<Skill[]>(
    appData?.globalSkills ?? []
  )
  const [projectMcps, setProjectMcps] = useState<Mcp[]>([])
  const [projectSkills, setProjectSkills] = useState<Skill[]>([])
  useEffect(() => {
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

  // Web-search config is GLOBAL, so it is resolved once by the app layout's
  // loader rather than per Composer mount — asking again on every session switch
  // both repeated a settled question and flashed the pill in a beat after paint.
  // Seeded into state so the fallback below can fill it when this Composer is
  // mounted outside that layout.
  const [searchSettings, setSearchSettings] = useState<SearchSettings | null>(
    appData?.searchSettings ?? null
  )
  // Show the "search not configured" hint ONLY when search is on and the
  // selected provider genuinely cannot run — i.e. it needs a key and has none.
  // Providers with a keyless tier (Tavily, the default; arxiv, which needs no
  // credential at all) work as-is, so warning about them would be false: the
  // user is told to fix something that is not broken, on the very first screen.
  const searchNeedsKey =
    !!searchSettings?.enabled &&
    !searchSettings.has_key &&
    !searchSettings.supports_keyless &&
    searchSettings.provider !== 'arxiv'

  useEffect(() => {
    // Everything here already arrived with the layout loader on the normal
    // path; this only covers a Composer mounted outside that layout, where
    // there is no loader data to seed from.
    if (hasAppData) return
    Promise.all([api.listProviders(), api.listModels(), api.getAgentSettings()])
      .then(([ps, ms, s]) => {
        setProviders(ps)
        setModels(ms)
        setSettings(s)
      })
      // `null` is what makes ModelSelector show a skeleton, so leaving it there
      // on failure means a picker that never stops loading. `[]` lets it say
      // there is nothing to pick, which is at least a resolved answer.
      .catch(() => {
        setProviders([])
        setModels([])
      })
    api
      .listMcps('global')
      .then(setGlobalMcps)
      .catch(() => setGlobalMcps([]))
    api
      .listSkills('global')
      .then(setGlobalSkills)
      .catch(() => setGlobalSkills([]))
    api
      .getSearchSettings()
      .then(setSearchSettings)
      .catch(() => setSearchSettings(null))
    if (hasProjectPicker) {
      // Already `[]`, so this only keeps the rejection from going unhandled.
      api
        .listProjects()
        .then(setProjects)
        .catch(() => setProjects([]))
    }
  }, [hasProjectPicker, hasAppData])

  const selectModel = async (providerId: string, modelId: string) => {
    try {
      setSettings(await modelSelection.select(providerId, modelId))
      void revalidator.revalidate()
    } catch {
      /* API errors are shown by the shared error toast. */
    }
  }

  // Slash-command suggestions list EVERY known skill (global + project),
  // enabled or not. Invoking one with `/` force-enables it for that turn, so
  // gating the list on `enabled` only hid skills the user could legitimately
  // reach — unlike the pill's popover, which reports what is currently on.
  const skillSuggestions = useMemo(
    () =>
      mergedSkills.map((s) => ({
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

  // The panel scrolls (it is height-capped), so arrowing past its edge would
  // move the highlighted row out of sight. Keep the active row in view — but
  // only for keyboard moves: hover updates the index too, and nudging the list
  // under a resting pointer would fight the mouse.
  const suggestListRef = useRef<HTMLDivElement>(null)
  const activeSuggestRef = useRef<HTMLDivElement>(null)
  const suggestKeyNavRef = useRef(false)

  useEffect(() => {
    if (!suggestKeyNavRef.current) return
    suggestKeyNavRef.current = false
    const list = suggestListRef.current
    const item = activeSuggestRef.current
    if (!list || !item) return
    // Both ends snap all the way, so wrapping around lands on a clean edge with
    // the panel's own padding visible instead of the row flush against it.
    if (suggestIndex === 0) {
      list.scrollTop = 0
      return
    }
    if (suggestIndex === filteredSuggestions.length - 1) {
      list.scrollTop = list.scrollHeight
      return
    }
    // Scrolled by hand rather than `scrollIntoView`: the panel lives in a body
    // portal, so the browser would happily scroll the page behind it too.
    const listBox = list.getBoundingClientRect()
    const itemBox = item.getBoundingClientRect()
    if (itemBox.top < listBox.top) {
      list.scrollTop -= listBox.top - itemBox.top
    } else if (itemBox.bottom > listBox.bottom) {
      list.scrollTop += itemBox.bottom - listBox.bottom
    }
  }, [suggestIndex, filteredSuggestions.length])

  // Editing the query reshuffles the list, so an index carried over from the
  // previous set can point past its end (Enter would then pick nothing). Snap
  // the selection — and the scroll position — back to the top.
  useEffect(() => {
    setSuggestIndex(0)
    if (suggestListRef.current) suggestListRef.current.scrollTop = 0
  }, [filteredSuggestions])

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
          suggestKeyNavRef.current = true
          setSuggestIndex((i) => (i + 1) % filteredSuggestions.length)
          break
        case 'ArrowUp':
          e.preventDefault()
          suggestKeyNavRef.current = true
          setSuggestIndex(
            (i) =>
              (i - 1 + filteredSuggestions.length) % filteredSuggestions.length
          )
          break
        case 'Enter': {
          const picked = filteredSuggestions[suggestIndex]
          if (!picked) return
          e.preventDefault()
          e.stopPropagation()
          selectSuggestion(picked)
          break
        }
        case 'Escape':
          e.preventDefault()
          closeSuggestions()
          break
      }
    },
    [filteredSuggestions, suggestIndex, selectSuggestion, closeSuggestions]
  )

  // Default the picker to the default project when nothing is picked yet.
  // `effectiveProject` already reads through to it, but the pick still has to be
  // committed here: this is what tells the host, which routes the project_id the
  // request is sent with.
  useEffect(() => {
    if (hasProjectPicker && defaultProject && pickedProjectId === null) {
      setPickedProjectId(defaultProject.id)
      onProjectChange?.(defaultProject.id)
    }
  }, [hasProjectPicker, defaultProject, pickedProjectId, onProjectChange])

  // The project files land in: fixed project, or the picked one on the homepage
  // new-chat. Derived from `effectiveProject` so uploads and the pills can never
  // disagree about which project is meant — including the default the effect
  // above has yet to commit.
  const effectiveProjectId = effectiveProject?.id ?? null

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
      // See updateSettings: the loader snapshot backing `projects` must not stay
      // on the old mode, or the composer remounted by the first message reads it
      // back out of `effectiveProject`.
      revalidator.revalidate()
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

  // Pressing Enter with no usable model has nothing to hover, so the tooltip is
  // opened programmatically for a moment. Hover keeps working on its own
  // (uncontrolled `open` would kill that, hence the timer resetting to false).
  const [modelHintOpen, setModelHintOpen] = useState(false)
  useEffect(() => {
    if (!modelHintOpen) return
    const timer = setTimeout(() => setModelHintOpen(false), 2500)
    return () => clearTimeout(timer)
  }, [modelHintOpen])

  const hasUploading = files.some((f) => f.status === 'uploading')
  const hasReadyFiles = files.some((f) => f.status === 'done')
  // No usable model — the settings pointer names a model that is no longer in
  // the catalog (deleting the active model leaves the pointer behind) or names
  // nothing at all. The backend would silently fall back to whatever its config
  // still holds, so the turn "works" while the UI shows no model: block sending
  // instead and say why. `null` = still loading, which must not block.
  // The active model's "image understanding" switch. Two states, default off:
  // anything that is not an explicit `true` means the images travel as paths.
  // (This used to test `=== false` only, because an unset model still had a
  // third meaning — "let the SDK decide", which in practice sent images. Now
  // unset simply is off, so the notice has to cover it or it would go missing
  // for exactly the models most likely to need it.)
  const activeModel =
    models !== null && settings !== null
      ? models.find((m) => m.id === settings.default_model_id)
      : undefined
  const visionOff = activeModel !== undefined && !activeModel.supports_vision
  const hasImageFile = files.some((f) => (f.type ?? '').startsWith('image'))
  const modelMissing =
    models !== null &&
    settings !== null &&
    (!models.some((m) => m.id === settings.default_model_id) ||
      providers?.find((p) => p.id === selectedProvider)?.enabled === false)
  // Send is allowed when nothing is still uploading and there is text, a
  // ready file, or a picked skill pill (a bare skill invocation is valid —
  // the backend answers with the skill intro).
  const canSend =
    !preparing &&
    !hasUploading &&
    !modelMissing &&
    (!!draft.trim() || hasReadyFiles || pickedSkills.length > 0)

  /** Turn on image understanding for the active model, in place.
   *
   * This used to navigate to Settings → Models. That route unmounts the
   * composer, and both the draft and the attached files live in plain component
   * state — so following our own suggestion threw away the message the user was
   * in the middle of writing and left an orphaned upload in the workspace. The
   * setting is one boolean on one model; there is nothing here worth a round
   * trip through another page. */
  // Refresh the catalog without replacing this conversation's selection.
  useModelChanged(
    useCallback(() => {
      Promise.all([
        api.getAgentSettings(),
        api.listModels(),
        api.listProviders()
      ])
        .then(([settings, models, providers]) => {
          setSettings(settings)
          setModels(models)
          setProviders(providers)
        })
        .catch(() => {})
    }, [])
  )

  const enableVision = async () => {
    if (!activeModel) return
    try {
      const updated = await api.updateModel(activeModel.id, {
        supports_vision: true
      })
      setModels((prev) =>
        (prev ?? []).map((m) => (m.id === updated.id ? updated : m))
      )
      // See updateSettings: `models` is seeded from the loader snapshot, so
      // leaving it stale means the next composer instance reads the model as
      // vision-less again and asks the user to enable what they just enabled.
      revalidator.revalidate()
    } catch {
      message.error(t.errors.requestFailed)
    }
  }

  const handleSubmit = async (value: string) => {
    if (submitting.current) return
    const text = value.trim()
    if (hasUploading) return
    // Enter reaches here without passing the button's disabled state, so the
    // guard is repeated — and surfaces the same tooltip the button shows, since
    // a keystroke that silently does nothing reads as a broken composer.
    if (modelMissing) {
      setModelHintOpen(true)
      return
    }
    // ORDER IS PART OF THE CONTRACT: the backend numbers image attachments
    // "Image 1..N" in the order they arrive here, and the model answers "the
    // second image" against that numbering. `files` is in the order the user
    // picked them (addFiles appends; uploadOne only patches an entry in place,
    // so a fast upload never jumps ahead of a slow one), and filter/map both
    // preserve it — which is what keeps the numbering aligned with the chips the
    // user is looking at. Do not sort or re-group this list.
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
    submitting.current = true
    setPreparing(true)
    try {
      const modelId = await modelSelection.ready()
      await onSubmit(text, refs, hasSkill ? segments : undefined, modelId)
    } catch {
      message.error(t.errors.requestFailed)
      return
    } finally {
      submitting.current = false
      setPreparing(false)
    }
    setDraft('')
    setFiles([])
    setPickedSkills([])
    // Slot mode is uncontrolled; clear the editable area imperatively.
    senderRef.current?.clear()
  }

  /** Paste a multi-line block WITH its line breaks.
   *
   * Sender's slot mode is a contenteditable, and its own paste handler pipes
   * the clipboard text through a cleaner that strips every `\n` — so pasting
   * a paragraph arrived as one squashed line. Line breaks themselves are fully
   * supported in that editable area (Shift+Enter inserts a real `\n` text node,
   * and the area is `white-space: pre-wrap`), so paste is the only gap.
   *
   * Runs in the CAPTURE phase to preempt Sender's own handler, then inserts the
   * text verbatim through the same imperative `insert()` used for skill pills —
   * which builds a plain text node, exactly what Shift+Enter produces. Only
   * multi-line text is intercepted; single-line text and pasted files keep
   * Sender's built-in handling (`onPasteFile` below). */
  const handlePasteCapture = (e: React.ClipboardEvent) => {
    const text = e.clipboardData?.getData('text/plain') ?? ''
    // Normalize CRLF/CR first: a Windows clipboard would otherwise leave stray
    // \r characters in the value the model receives.
    const normalized = text.replace(/\r\n?/g, '\n')
    if (!normalized.includes('\n')) return
    e.preventDefault()
    e.stopPropagation()
    senderRef.current?.insert(
      [{ type: 'text', value: normalized.replace(/\u200B/g, '') }],
      'cursor'
    )
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

  // Backspace on an empty editable area peels off attachments one at a time
  // (last-added first), the familiar chip-input behaviour. Only fires when the
  // area is truly empty — no text AND no skill pills — so pill backspacing (the
  // Sender's own handling) is never pre-empted.
  const backspaceRemovesFile =
    draft === '' && pickedSkills.length === 0 && files.length > 0
  const removeLastFile = () => {
    setFiles((prev) => prev.slice(0, -1))
  }

  const projectMenuItems: MenuProps['items'] = hasProjectPicker
    ? [
        // One flat list: the default project is listed inline with the rest
        // instead of being hoisted into its own section above a divider.
        ...projects.map((p) => ({
          key: p.id,
          icon: <FolderIcon className="h-4 w-4" />,
          // Capped + truncated: an antd menu sizes itself to its widest row, so
          // one long project name stretched the whole panel past the viewport.
          // The full name stays reachable via the row's native tooltip.
          label: (
            <span
              className="block max-w-[240px] text-xs truncate"
              title={p.name}
            >
              {p.name}
            </span>
          ),
          onClick: () => {
            setPickedProjectId(p.id)
            onProjectChange?.(p.id)
          }
        })),
        ...(projects.length > 0 ? [{ type: 'divider' as const }] : []),
        {
          key: '__create__',
          icon: <AddIcon className="h-4 w-4" />,
          label: <span className="text-xs">{t.home.createProject}</span>,
          onClick: () => setCreateOpen(true)
        }
      ]
    : undefined

  // The picker's own label, named once so the trigger can both render it
  // truncated and hand the full string to its tooltip. No separate default
  // fallback: `effectiveProject` resolves it, and it is only rendered under
  // `hasProjectPicker`, so reaching the placeholder means there are no projects.
  const pickerLabel = effectiveProject?.name ?? t.home.noProject

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
            {/* The WHOLE row toggles the accordion (not just the text block), so
                the hover state spans the full width. The running-task caption
                lives inside the button for the same reason — as a sibling it
                claimed the remaining width and left that part of the row dead.
                `-mx-2 px-2` lets the hover fill bleed slightly past the text
                without shifting its optical alignment. */}
            <button
              type="button"
              onClick={() => setThinkingExpanded((v) => !v)}
              className="-mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-center justify-between gap-2 rounded-lg border-none bg-transparent px-2 py-1 text-left outline-none"
            >
              <span className="flex shrink-0 items-center gap-1">
                <IconTask className="h-5.5 w-5.5" />
                <span className="text-sm font-medium text-msa-text-1">
                  {t.home.thinkingTasks}
                </span>
                <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-xs text-msa-text-3">
                  {doneCount}/{totalCount}
                </span>
                <ExpandIcon
                  className={`ml-1 h-3.5 w-3.5 text-msa-text-3 transition-transform ${
                    thinkingExpanded ? '' : 'rotate-180'
                  }`}
                />
              </span>
              <span className="flex w-0 flex-1 justify-end">
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
              </span>
            </button>

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
            {/* Full-width hit area + hover fill, matching the tasks header. */}
            <button
              type="button"
              onClick={() => setFilesExpanded((v) => !v)}
              className="-mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-center gap-1 rounded-lg border-none bg-transparent px-2 py-1 text-left outline-none"
            >
              <IconFolder className="h-5.5 w-5.5" />
              <span className="ml-1 text-sm font-medium text-msa-text-1">
                {t.home.thinkingFiles}
              </span>
              <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-xs text-msa-text-3">
                {thinking.files.length}
              </span>
              <ExpandIcon
                className={`ml-1 h-3.5 w-3.5 text-msa-text-3 transition-transform ${
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
        <div className="composer-card relative flex flex-col rounded-3xl border border-msa-line-1 bg-msa-bg-1 p-5 shadow-msa-m">
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
                  className="!max-w-[240px] !text-xs !text-msa-text-3"
                  title={pickerLabel}
                >
                  <span className="min-w-0 truncate">{pickerLabel}</span>
                  <CaretDownIcon
                    className={`ml-1 h-2.25 w-2.25 shrink-0 transition-transform duration-200 ${
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
              popupRender={() => (
                <div
                  ref={suggestListRef}
                  className="max-h-52 w-fit max-w-[min(420px,80cqw)] overflow-y-auto rounded-2xl border border-msa-line-1 bg-msa-bg-1 p-2 shadow-msa-m"
                >
                  {filteredSuggestions.map((item, idx) => (
                    <div
                      key={item.value}
                      ref={idx === suggestIndex ? activeSuggestRef : undefined}
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
              <div onPasteCapture={handlePasteCapture}>
                {modelSelection.saveFailed && (
                  <p role="alert" className="mb-2 text-xs text-msa-text-2">
                    {t.home.modelSaveFailed}
                  </p>
                )}
                <StableSender
                  ref={senderRef}
                  disabled={preparing}
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
                    // Empty input + attachments: Backspace removes the last
                    // attachment instead of doing nothing.
                    if (e.key === 'Backspace' && backspaceRemovesFile) {
                      e.preventDefault()
                      removeLastFile()
                      return false
                    }
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
                        {/* One notice for the whole group rather than a
                            per-chip tooltip: the user has to learn this BEFORE
                            sending, and a tooltip is easy to never hover.
                            The remedy is a button rather than a longer
                            sentence — the settings page is one click away, so
                            explaining the route costs more words than walking
                            it. */}
                        {visionOff && hasImageFile ? (
                          <div className="w-full text-[11px] leading-snug text-amber-600 dark:text-amber-500">
                            {t.home.visionOffNotice}{' '}
                            <button
                              type="button"
                              onClick={enableVision}
                              className="cursor-pointer border-none bg-transparent p-0 text-[11px] font-medium leading-snug text-amber-700 underline underline-offset-2 outline-none dark:text-amber-400"
                            >
                              {t.home.visionOffAction}
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ) : undefined
                  }
                  footer={
                    // @container: makes this footer an inline-size query
                    // container, so both the pills' width cap (cqw) and the
                    // collapse threshold below resolve against the composer column
                    // rather than the viewport — the composer can be narrow while
                    // the viewport stays wide (e.g. a detail rail is open), where a
                    // viewport-relative rule overflows or wraps.
                    <div className="@container relative flex items-center justify-between gap-2 pt-3">
                      {/* Left: pills. Collapsed behind a toggle while the footer
                          is narrower than the row needs, inline above that.

                          The threshold is a query on the footer's own inline size,
                          NOT a viewport breakpoint: the composer takes the full
                          width of a column the rail can squeeze to ~340px while the
                          viewport stays wide, and a `md:` breakpoint read as "wide
                          viewport, so keep the pills inline" and let them wrap into
                          three rows there.

                          550px is the threshold: the four standing pills plus the
                          ~90px attach/send cluster fit inline in a fairly narrow
                          column, so opening the workspace panel (which splits the
                          chat column) no longer collapses them into the toggle right
                          away. Above it the pills shrink to one line; below it
                          collapses to the scroll row. A session can carry two more
                          pills, so this is the common case, not a guarantee.

                          Visibility is CSS-driven so the first paint is correct with
                          no SSR/hydration flash. When expanded on a narrow footer
                          the group floats above the row.

                          That float is pinned to the row's own width (`inset-x-0`)
                          and scrolls sideways as ONE line. It used to be a wrapping
                          block of shrink-to-fit width, and since it is anchored at
                          `bottom-0` every extra row grew upwards — at 390px a
                          session's five pills took three rows and poked 25px out
                          through the composer's top border (45px / four rows at
                          320px), which read as a stray grey slab floating over the
                          transcript. One line can never do that, whatever the pill
                          count or label length.

                          Pills never wrap: `flex-nowrap` plus `min-w-0` on every
                          wrapper let an over-long row shrink each pill to its
                          `min-w-24` floor and truncate the label instead of spilling
                          onto a second line. */}
                      <div
                        ref={pillsRef}
                        className={`flex items-center gap-2.5 ${
                          pillsExpanded
                            ? 'absolute inset-x-0 bottom-0 z-10 min-w-0 flex-nowrap overflow-x-auto bg-msa-bg-1 pt-3 @min-[550px]:static @min-[550px]:overflow-x-visible @min-[550px]:bg-transparent @min-[550px]:pt-0'
                            : 'min-w-0 flex-nowrap'
                        }`}
                      >
                        {/* Toggle button: shown only while collapsed */}
                        {!pillsExpanded && (
                          <IconButton
                            className="@min-[550px]:hidden"
                            icon={<MoreIcon className="h-5 w-5" />}
                            onClick={() => setPillsExpanded(true)}
                          />
                        )}

                        <div
                          className={`flex items-center gap-2.5 ${
                            pillsExpanded
                              ? 'w-max shrink-0 min-w-0 flex-nowrap @min-[550px]:w-auto @min-[550px]:shrink'
                              : 'hidden min-w-0 flex-nowrap @min-[550px]:flex'
                          }`}
                        >
                          {/* Model pill */}
                          <ModelSelector
                            disabled={preparing || modelSelectionDisabled}
                            models={models}
                            providers={providers}
                            settings={settings}
                            onSelectModel={selectModel}
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
                            classNames={{
                              itemContent: 'text-xs'
                            }}
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

                          {/* Search-not-configured hint: only when search is on
                              but its provider has no key. Uses PillButton (not a
                              hand-rolled button) so the background, padding and
                              height match the selector pills exactly — copying its
                              classes by hand drifted on all of them. `caret={false}`:
                              it navigates rather than opening a panel. */}
                          {searchNeedsKey && (
                            <Tooltip title={t.home.searchUnconfiguredTip}>
                              <PillButton
                                caret={false}
                                onClick={() => navigate('/settings/search')}
                                icon={<EditIcon className="h-4 w-4" />}
                                className="!text-msa-text-3"
                              >
                                {t.home.searchUnconfigured}
                              </PillButton>
                            </Tooltip>
                          )}
                        </div>
                      </div>

                      {/* Right: attach + send */}
                      <div className="flex items-center gap-4">
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
                                icon={<AddIcon className="h-5 w-5" />}
                                variant="tonal"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isMaxFiles}
                              />
                            </Tooltip>
                          </>
                        )}
                        <Tooltip
                          // `open` is only forced for the no-model hint (Enter has
                          // no hover to rely on); otherwise undefined leaves the
                          // tooltip in its normal hover mode.
                          open={
                            modelMissing && modelHintOpen ? true : undefined
                          }
                          title={
                            loading
                              ? t.home.stop
                              : modelMissing
                                ? t.home.modelRequired
                                : t.home.send
                          }
                        >
                          {loading ? (
                            <IconButton
                              variant="primary"
                              icon={
                                <span className="block h-2.5 w-2.5 rounded-[2px] bg-current" />
                              }
                              onClick={() => onCancel?.()}
                            />
                          ) : (
                            // A disabled button fires no pointer events, so the
                            // wrapper is what the tooltip hovers on — without it
                            // the "pick a model" hint would be unreachable.
                            <span
                              onMouseEnter={() => {
                                if (modelMissing) setModelHintOpen(true)
                              }}
                            >
                              <IconButton
                                variant="primary"
                                icon={<SendIcon className="h-5 w-5" />}
                                onClick={() => handleSubmit(draft)}
                                disabled={!canSend}
                              />
                            </span>
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
            // The local push above only feeds this picker. `projects` is loader
            // data, and the sidebar renders from it — without this the new
            // project is missing there, and the next composer instance seeds
            // from the snapshot and drops it from the picker too.
            revalidator.revalidate()
          }}
        />
      )}
    </>
  )
}
