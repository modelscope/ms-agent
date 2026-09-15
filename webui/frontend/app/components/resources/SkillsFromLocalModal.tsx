import { App, Button, Input, Modal, Segmented } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '~/lib/api'
import { collectDroppedEntries } from '~/lib/dropFiles'
import type { DroppedFile } from '~/lib/dropFiles'
import { useHosted } from '~/lib/hosted'
import { useT } from '~/lib/i18n'
import type { Scope, Skill } from '~/lib/types'
import UploadIcon from '~/assets/icons/upload.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'
import FolderIcon from '~/assets/icons/folder.svg?react'

// A skill IS a directory: its folder name becomes the skill name and its
// SKILL.md carries the metadata. So only folders can be imported — a lone file
// has nothing to name the skill after (and the backend bundle expects the tree).
//
// Files keep the path they had INSIDE the pick: the backend locates SKILL.md and
// re-roots the bundle on its directory, so a flattened list would collapse
// `scripts/run.py` to `run.py` and destroy the skill's layout.
type LocalPick = {
  uid: string
  name: string
  files: DroppedFile[]
}

// Both modes end as owned copies in the scope's skills tree. Upload sends the
// browser-selected bytes; path import asks the backend to discover and copy
// every Skill under a directory it can read. Making the choice explicit keeps
// `submit` from silently discarding one input when both have values.
type ImportMode = 'upload' | 'path'

interface Props {
  open: boolean
  scope: Scope
  onClose: () => void
  onImported: (skill: Skill) => void
}

const BUNDLE_FORMAT = 'webui.skill.bundle.v1'

function relativePath(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string })
    .webkitRelativePath
  return rel || file.name
}

async function bundleContent(files: DroppedFile[]): Promise<string> {
  const payloadFiles = await Promise.all(
    files.map(async ({ file, path }) => ({
      path,
      content: await file.text()
    }))
  )
  return JSON.stringify({ format: BUNDLE_FORMAT, files: payloadFiles })
}

// A best-effort match of the server's collision rule, used ONLY to pre-warn with
// the "exists" tag. It deliberately does NOT replicate the server's directory
// naming (control chars, Windows reserveds, length caps): duplicating those
// rules is what let the two sides drift apart before, flagging conflicts the
// server allowed and missing ones it rejected. The real guard is the 409 the
// import returns — see `submit`.
function nameKey(value: string): string {
  return value.trim().replace(/\s+/g, '-').toLowerCase()
}

/** The name the backend will use for this pick: SKILL.md's frontmatter `name`
 * when present, else the folder name. Read client-side because the file
 * contents are already being read for the bundle anyway. */
async function resolveSkillName(pick: LocalPick): Promise<string> {
  const md = pick.files.find(({ path }) => path.split('/').pop() === 'SKILL.md')
  if (!md) return pick.name
  try {
    const text = await md.file.text()
    // Only the leading frontmatter block counts, same as the SDK's parser.
    const fm = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text)
    const name = fm && /^name:\s*(.+)$/m.exec(fm[1])?.[1]
    return name ? name.trim().replace(/^['"]|['"]$/g, '') : pick.name
  } catch {
    return pick.name
  }
}

export function SkillsFromLocalModal({
  open,
  scope,
  onClose,
  onImported
}: Props) {
  const { t } = useT()
  const { message, modal } = App.useApp()
  // Hosted: 'path' would ask the server to copy a directory on its own disk,
  // which the user cannot browse and did not put there — so upload is the only
  // mode offered. `mode` still exists (both branches below are unchanged); it
  // simply stays on its 'upload' default because nothing can switch it.
  const hosted = useHosted()
  const [mode, setMode] = useState<ImportMode>('upload')
  const [picks, setPicks] = useState<LocalPick[]>([])
  const [localPath, setLocalPath] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [dragging, setDragging] = useState(false)
  const folderInputRef = useRef<HTMLInputElement | null>(null)
  // Names already taken in the target scope. Loaded per open (and per scope)
  // because the list changes as skills are imported/removed elsewhere.
  const [takenNames, setTakenNames] = useState<Set<string>>(new Set())
  // Resolved SKILL.md name per pick uid — async (it reads the file), so the row
  // renders from this map rather than recomputing during render.
  const [pickNames, setPickNames] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!open) return
    setMode('upload')
    setPicks([])
    setLocalPath('')
    setDragging(false)
    setPickNames({})
    api
      .listSkills(scope)
      .then((rows) => setTakenNames(new Set(rows.map((s) => nameKey(s.name)))))
      .catch(() => setTakenNames(new Set()))
  }, [open, scope])

  // Only the active mode's input counts, so "Import" can state up front whether
  // there is anything to import instead of quietly closing on an empty submit.
  const ready = mode === 'upload' ? picks.length > 0 : localPath.trim() !== ''

  // Callback ref: the folder input lives inside a `destroyOnHidden` Modal, so it
  // is created *after* mount (and re-created each open). A one-shot useEffect([])
  // runs while the input doesn't exist yet and never sets these attributes — so
  // "pick folder" silently opened a file picker. Applying them on every mount of
  // the element fixes directory selection.
  const attachFolderInput = (el: HTMLInputElement | null) => {
    folderInputRef.current = el
    if (el) {
      el.setAttribute('webkitdirectory', '')
      el.setAttribute('directory', '')
    }
  }

  /** Import the given picks. Returns the picks the server refused as name
   * conflicts (409) instead of throwing on them, so the caller can offer to
   * replace exactly those. */
  const importPicks = async (
    batch: LocalPick[],
    overwrite: boolean
  ): Promise<{ last: Skill | null; conflicted: LocalPick[] }> => {
    let last: Skill | null = null
    const conflicted: LocalPick[] = []
    for (const pick of batch) {
      try {
        last = await api.createSkill(
          {
            name: pick.name,
            kind: 'bundle',
            content: await bundleContent(pick.files),
            enabled: true,
            scope,
            overwrite
          },
          // Handled here as a question, not an error: `silent` keeps the global
          // toast from firing behind the confirm dialog.
          { silent: [409] }
        )
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          conflicted.push(pick)
          continue
        }
        throw err
      }
    }
    return { last, conflicted }
  }

  /** Ask before replacing, then retry only the picks that collided. */
  const confirmOverwrite = (batch: LocalPick[]) => {
    const names = batch.map((p) => pickNames[p.uid] ?? p.name).join('\u3001')
    modal.confirm({
      title: t.skillImport.duplicateTitle,
      content: t.skillImport.duplicateContent.replace('{names}', names),
      okText: t.skillImport.duplicateOk,
      okButtonProps: { danger: true },
      cancelText: t.resources.cancel,
      onOk: async () => {
        setSubmitting(true)
        try {
          const { last } = await importPicks(batch, true)
          if (last) onImported(last)
        } catch {
          // Non-409 failures surface via the global toast (root ApiErrorBridge).
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  const confirmPathOverwrite = () => {
    modal.confirm({
      title: t.skillImport.duplicateTitle,
      content: t.skillImport.pathDuplicateContent,
      okText: t.skillImport.duplicateOk,
      okButtonProps: { danger: true },
      cancelText: t.resources.cancel,
      onOk: async () => {
        setSubmitting(true)
        try {
          const rows = await api.importSkillsFromPath({
            path: localPath.trim(),
            scope,
            overwrite: true
          })
          const last = rows.at(-1)
          if (last) onImported(last)
        } catch {
          // API errors surface via the global toast.
        } finally {
          setSubmitting(false)
        }
      }
    })
  }

  /** The server is the authority on collisions: it answers 409 and this reacts,
   * rather than deciding from a client-side copy of its naming rules. The
   * "exists" tag is only a pre-warning — it reads listed skill NAMES, while the
   * server also knows about skills registered from nested/external sources, so
   * the two can legitimately disagree. Replacement is a staged swap server-side:
   * the existing skill survives untouched if the new bundle fails to load. */
  const submit = async () => {
    if (!ready) return
    setSubmitting(true)
    try {
      if (mode === 'path') {
        try {
          const rows = await api.importSkillsFromPath(
            { path: localPath.trim(), scope, overwrite: false },
            { silent: [409] }
          )
          const last = rows.at(-1)
          if (last) onImported(last)
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            confirmPathOverwrite()
            return
          }
          throw err
        }
        return
      }
      // ONE SKILL PER FOLDER. Merging the picks into a single bundle (what this
      // did before) produced one skill named after the first folder, carrying
      // every folder's files — the backend picks the first SKILL.md it finds and
      // re-roots everything on that directory, so the rest arrived mangled.
      const { last, conflicted } = await importPicks(picks, false)
      if (conflicted.length > 0) {
        confirmOverwrite(conflicted)
        return
      }
      if (last) onImported(last)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    } finally {
      setSubmitting(false)
    }
  }

  const addFolder = (name: string, files: DroppedFile[]) => {
    if (files.length === 0) return
    const pick: LocalPick = {
      uid: `${name}-${Date.now()}-${files.length}`,
      name,
      files
    }
    setPicks((prev) => [...prev, pick])
    // Resolve the real skill name in the background; the row shows the folder
    // name until it lands, and the "exists" check re-runs when it does.
    resolveSkillName(pick).then((resolved) =>
      setPickNames((prev) => ({ ...prev, [pick.uid]: resolved }))
    )
  }

  const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length === 0) return
    const rel = relativePath(files[0])
    // The picker fills webkitRelativePath (`my-skill/SKILL.md`), which is the
    // same shape the entry-tree walk produces for a drop.
    addFolder(
      rel.includes('/') ? rel.split('/')[0] : 'folder',
      files.map((file) => ({ file, path: relativePath(file) }))
    )
    e.target.value = ''
  }

  // Folder drops only. `DataTransfer.files` cannot tell a directory from a file
  // (a dropped folder arrives as one unreadable 96 B "file"), which is why a
  // folder used to be listed as a file here — collectDroppedEntries walks the
  // real entry tree instead, so we know which is which.
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(false)
    const entries = await collectDroppedEntries(e.dataTransfer)
    const folders = entries.filter((entry) => entry.isDirectory)
    if (folders.length === 0) {
      if (entries.length > 0) message.warning(t.skillImport.localFolderOnly)
      return
    }
    for (const folder of folders) addFolder(folder.name, folder.files)
    // Loose files alongside a folder are ignored rather than silently bundled.
    if (folders.length !== entries.length)
      message.warning(t.skillImport.localFolderOnly)
  }

  const removePick = (uid: string) =>
    setPicks((prev) => prev.filter((pick) => pick.uid !== uid))

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t.skillImport.localTitle}
      okText={t.skillImport.localUpload}
      cancelText={t.resources.cancel}
      onOk={submit}
      okButtonProps={{ loading: submitting, disabled: !ready }}
      destroyOnHidden
      width={560}
    >
      {/* Dropped entirely when hosted rather than reduced to its single
          remaining option: a one-choice switch reads as a control that is
          broken, not as one mode being unavailable. */}
      {!hosted && (
        <Segmented<ImportMode>
          value={mode}
          onChange={setMode}
          options={[
            { value: 'upload', label: t.skillImport.localModeUpload },
            { value: 'path', label: t.skillImport.localModePath }
          ]}
          className="mb-2"
        />
      )}
      <p className="mb-3 text-xs text-msa-text-3">
        {mode === 'upload'
          ? t.skillImport.localUploadHint
          : t.skillImport.localPathHint}
      </p>

      {mode === 'upload' ? (
        <>
          {/* Plain drop zone rather than antd's Upload.Dragger: the Dragger funnels
              every drop through `beforeUpload(file)`, which can neither tell a
              folder from a file nor reject one.
              The whole area is the control — with only one possible action (pick a
              folder) a separate button inside it would just be a second way to do
              the same thing. */}
          <div
            role="button"
            tabIndex={0}
            className={`flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-10 transition-colors hover:border-msa-purple-5 ${
              dragging
                ? 'border-msa-purple-5 bg-msa-fill-2'
                : 'border-msa-line-1 bg-msa-fill-1'
            }`}
            onClick={() => folderInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                folderInputRef.current?.click()
              }
            }}
            onDragOver={(e) => {
              if (!e.dataTransfer.types.includes('Files')) return
              e.preventDefault()
              e.dataTransfer.dropEffect = 'copy'
              if (!dragging) setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <UploadIcon className="h-[32px] w-[32px] text-msa-text-brand1" />
            <p className="m-0 my-1 text-sm text-msa-text-2">
              {t.skillImport.localDropHint}
            </p>
          </div>

          <input
            ref={attachFolderInput}
            type="file"
            className="hidden"
            multiple
            onChange={handleFolderChange}
          />

          {picks.length > 0 && (
            <ul className="mt-3 max-h-[260px] list-none space-y-2 overflow-y-auto p-0">
              {picks.map((pick) => (
                <li
                  key={pick.uid}
                  className="flex items-center gap-2 rounded-lg border border-msa-line-1 px-3 py-2.5 text-sm"
                >
                  <FolderIcon className="h-5 w-5" />
                  <span className="flex-1 truncate text-msa-text-1">
                    {pick.name}
                  </span>
                  {/* Warns BEFORE the click that this name is taken — the import
                      would otherwise appear to succeed while the new copy stays
                      hidden behind the existing skill. */}
                  {takenNames.has(nameKey(pickNames[pick.uid] ?? pick.name)) && (
                    <span className="shrink-0 rounded bg-msa-fill-2 px-1.5 py-0.5 text-[10px] font-normal text-msa-deco-yellow">
                      {t.skillImport.duplicateTag}
                    </span>
                  )}
                  <span className="shrink-0 text-msa-text-3">
                    {`${pick.files.length} ${t.skillImport.localFolderFiles}`}
                  </span>
                  <Button
                    type="text"
                    size="small"
                    icon={<CloseIcon className="h-3.5 w-3.5" />}
                    className="!text-msa-text-3"
                    onClick={() => removePick(pick.uid)}
                  />
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <Input
          value={localPath}
          onChange={(e) => setLocalPath(e.target.value)}
          placeholder={t.skillImport.localPathPlaceholder}
        />
      )}

      <div className="mt-4">
        <p className="mb-2 text-sm font-semibold text-msa-text-1">
          {t.skillImport.localFileReqTitle}
        </p>
        <ul className="list-disc space-y-1 pl-5 text-xs text-msa-text-3">
          <li>{t.skillImport.localFileReq3}</li>
        </ul>
      </div>
    </Modal>
  )
}
