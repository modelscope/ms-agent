import { Drawer, Segmented, Select, Tooltip } from 'antd'
import type { TreeDataNode } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { CodeEditor } from '~/components/common/CodeEditor'
import { FolderTree } from '~/components/common/FolderTree'
import { Markdown } from '~/components/common/Markdown'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Skill } from '~/lib/types'
import ViewIcon from '~/assets/icons/view.svg?react'
import TerminalIcon from '~/assets/icons/terminal.svg?react'
import { languageFor } from '~/lib/editorLanguage'

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
    // Seed SKILL.md from the already-loaded skill body for an instant first
    // paint; the file list arrives async.
    setBodies({ 'SKILL.md': skill.content ?? '' })
    setFiles(['SKILL.md'])
    const seq = ++fetchSeq.current
    api
      .listSkillFiles(skill.id)
      .then((rows) => {
        if (seq !== fetchSeq.current) return
        if (rows.length) setFiles(rows.map((r) => r.path))
      })
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
      .catch(() => {})
  }, [open, skill, selected, bodies])

  const treeData = useMemo(() => buildTree(files), [files])
  const body = skill ? bodies[selected] : undefined

  const language = languageFor(selected)
  const isMarkdown = language === 'markdown'
  const isBinary = body === null

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
              {isMarkdown && !isBinary && (
                <Segmented<ViewMode>
                  size="small"
                  value={viewMode}
                  onChange={setViewMode}
                  options={[
                    {
                      value: 'preview',
                      icon: (
                        <Tooltip title={t.skillDetail.viewPreview}>
                          <ViewIcon className="h-4 w-4" />
                        </Tooltip>
                      )
                    },
                    {
                      value: 'code',
                      icon: (
                        <Tooltip title={t.skillDetail.viewCode}>
                          <TerminalIcon className="h-4 w-4" />
                        </Tooltip>
                      )
                    }
                  ]}
                />
              )}
            </header>
            <div className="min-h-0 flex-1 overflow-auto">
              {isBinary ? (
                <div className="flex h-full items-center justify-center text-sm text-msa-text-3">
                  {t.skillDetail.binaryFile}
                </div>
              ) : isMarkdown && viewMode === 'preview' ? (
                <div className="px-4 py-4 h-full">
                  <Markdown content={body ?? ''} frontmatter />
                </div>
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
