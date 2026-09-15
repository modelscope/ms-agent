import { Drawer, Segmented, Select, Tooltip } from 'antd'
import type { TreeDataNode } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
import { FolderTree } from '~/components/common/FolderTree'
import { HtmlPreview } from '~/components/common/HtmlPreview'
import { Markdown } from '~/components/common/Markdown'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Skill } from '~/lib/types'
import ViewIcon from '~/assets/icons/view.svg?react'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import { docKindFor, languageFor } from '~/lib/editorLanguage'
import { makeRefResolver } from '~/lib/previewRefs'

interface Props {
  open: boolean
  skill: Skill | null
  /** Sibling skills shown in the top-left switcher dropdown. */
  allSkills: Skill[]
  onClose: () => void
  onSkillChange: (skill: Skill) => void
}

type ViewMode = 'preview' | 'code'


/** Build a FolderTree data set from the backend's flat relative-path list.
 * Keys follow the FolderTree convention (`dir:<path>` / `file:<path>`) so the
 * tree infers icons itself. Directories first, then files, both sorted. */
function buildTree(paths: string[]): TreeDataNode[] {
  interface DirNode {
    dirs: Map<string, DirNode>
    files: string[] // full relative paths
  }
  const root: DirNode = { dirs: new Map(), files: [] }
  for (const p of paths) {
    const parts = p.split('/')
    let cur = root
    for (const part of parts.slice(0, -1)) {
      let next = cur.dirs.get(part)
      if (!next) {
        next = { dirs: new Map(), files: [] }
        cur.dirs.set(part, next)
      }
      cur = next
    }
    cur.files.push(p)
  }
  const toNodes = (node: DirNode, prefix: string): TreeDataNode[] => {
    const dirs = [...node.dirs.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, child]) => {
        const full = prefix ? `${prefix}/${name}` : name
        return {
          key: `dir:${full}`,
          title: name,
          children: toNodes(child, full)
        } as TreeDataNode
      })
    const files = [...node.files]
      .sort((a, b) => a.localeCompare(b))
      .map(
        (p) =>
          ({
            key: `file:${p}`,
            title: p.split('/').pop() ?? p,
            isLeaf: true
          }) as TreeDataNode
      )
    return [...dirs, ...files]
  }
  return toNodes(root, '')
}

export function SkillDetailDrawer({
  open,
  skill,
  allSkills,
  onClose,
  onSkillChange
}: Props) {
  const { t } = useT()
  const [selected, setSelected] = useState<string>('SKILL.md')
  const [viewMode, setViewMode] = useState<ViewMode>('preview')
  // Real relative paths of the skill's directory (from the backend).
  const [files, setFiles] = useState<string[]>(['SKILL.md'])
  // Fetched file bodies keyed by relative path; null ⇒ binary file.
  const [bodies, setBodies] = useState<Record<string, string | null>>({})
  const fetchSeq = useRef(0)

  useEffect(() => {
    if (!open || !skill) return
    setSelected('SKILL.md')
    setViewMode('preview')
    // Start with NO cached bodies. This used to seed
    // `bodies['SKILL.md'] = skill.content` as an "instant first paint", but
    // `content` on a discovered skill is its DESCRIPTION, not the file (see
    // backends/ms_agent/skills.py `_discovered_to_schema`) — so the pane showed a
    // single paragraph where the real document belongs. Worse, the lazy loader
    // below bails on `selected in bodies`, so the seed also SUPPRESSED the fetch
    // that would have corrected it: the first open only looked right by racing
    // (its effect still saw an empty `bodies` closure and fetched), while every
    // reopen re-seeded and stuck at the description.
    setBodies({})
    setFiles(['SKILL.md'])
    const seq = ++fetchSeq.current
    api
      .listSkillFiles(skill.id)
      .then((rows) => {
        if (seq !== fetchSeq.current) return
        if (rows.length) setFiles(rows.map((r) => r.path))
      })
      // Swallowed on purpose: `files` keeps its ['SKILL.md'] default, which is
      // a usable tree. Nothing is gated on this request resolving.
      .catch(() => {})
  }, [open, skill])

  // Lazy-load the selected file's content (cached per path).
  useEffect(() => {
    if (!open || !skill) return
    if (selected in bodies) return
    const seq = fetchSeq.current
    api
      .getSkillFile(skill.id, selected)
      .then((f) => {
        if (seq !== fetchSeq.current) return
        setBodies((prev) => ({ ...prev, [f.path]: f.content }))
      })
      .catch(() => {
        if (seq !== fetchSeq.current) return
        // Must record the path as fetched. `isLoading` below is
        // `!(selected in bodies)`, so bailing without writing anything leaves
        // the pane on its skeleton permanently — `''` renders as an empty file,
        // and the toast `api.ts` raises is what says the read failed.
        setBodies((prev) => ({ ...prev, [selected]: '' }))
      })
  }, [open, skill, selected, bodies])

  const treeData = useMemo(() => buildTree(files), [files])
  const body = skill ? bodies[selected] : undefined

  const language = languageFor(selected)
  const docKind = docKindFor(selected)
  const isBinary = body === null
  // Relative references in a skill document point at the skill's own files.
  const previewRefs = useMemo(
    () =>
      skill
        ? makeRefResolver(selected, (path) =>
            api.skillFileRawUrl(skill.id, path)
          )
        : undefined,
    [skill, selected]
  )
  // `undefined` = not fetched yet; `null` = binary; `''` = a genuinely empty
  // file. Only the first deserves a loading state — without this the pane
  // rendered an empty document while the request was in flight.
  const isLoading = skill != null && !(selected in bodies)

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="right"
      size="min(1100px, 100vw)"
      title={t.skillDetail.title}
      styles={{ body: { padding: 0 } }}
    >
      {!skill ? null : (
        <div className="flex h-full">
          <aside className="hidden w-60 shrink-0 flex-col border-r border-msa-line-1 lg:flex">
            <div className="p-2">
              <Select
                value={skill.id}
                onChange={(id) => {
                  const next = allSkills.find((s) => s.id === id)
                  if (next) onSkillChange(next)
                }}
                options={allSkills.map((s) => ({
                  value: s.id,
                  label: s.name
                }))}
                className="w-full"
                showSearch={{
                  optionFilterProp: 'label'
                }}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-2">
              <FolderTree
                treeData={treeData}
                selectedKey={`file:${selected}`}
                onSelect={(key) => {
                  if (!key.startsWith('file:')) return
                  setSelected(key.slice('file:'.length))
                  setViewMode('preview')
                }}
              />
            </div>
          </aside>

          <section className="flex min-w-0 flex-1 flex-col">
            <header className="flex shrink-0 items-center gap-1 border-b border-msa-line-1 px-3 py-2">
              <span className="truncate text-sm font-medium text-msa-text-1">
                {selected}
              </span>
              <span className="flex-1" />
              {docKind && !isBinary && (
                <Segmented<ViewMode>
                  size="small"
                  value={viewMode}
                  onChange={setViewMode}
                  options={[
                    {
                      value: 'preview',
                      icon: (
                        <Tooltip title={t.common.viewPreview}>
                          <ViewIcon className="h-5 w-5" />
                        </Tooltip>
                      )
                    },
                    {
                      value: 'code',
                      icon: (
                        <Tooltip title={t.common.viewCode}>
                          <TerminalIcon className="h-5 w-5" />
                        </Tooltip>
                      )
                    }
                  ]}
                />
              )}
            </header>
            <div className="min-h-0 flex-1 overflow-auto">
              {isLoading ? (
                <DeferredSkeleton rows={8} className="px-4 py-4" />
              ) : isBinary ? (
                <div className="flex h-full items-center justify-center text-sm text-msa-text-3">
                  {t.skillDetail.binaryFile}
                </div>
              ) : docKind === 'markdown' && viewMode === 'preview' ? (
                <div className="px-4 py-4 h-full">
                  <Markdown
                    content={body ?? ''}
                    frontmatter
                    resolveRef={previewRefs}
                  />
                </div>
              ) : docKind === 'html' && viewMode === 'preview' ? (
                <HtmlPreview
                  src={api.skillFileRawUrl(skill.id, selected)}
                  title={selected}
                />
              ) : (
                <div className="py-4 h-full">
                  <CodeEditor
                    value={body ?? ''}
                    language={language}
                    height="100%"
                    readOnly
                    fullFeatures
                  />
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </Drawer>
  )
}
