import { App, Button, Input, Modal, Segmented } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api } from '~/lib/api'
import { collectDroppedEntries } from '~/lib/dropFiles'
import type { DroppedFile } from '~/lib/dropFiles'
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

// The two sources are mutually exclusive and behave differently server-side:
// uploading COPIES the files into the scope's skills tree (kind 'bundle'),
// while a path REFERENCES a directory the backend can already read (kind
// 'source', registered via add_source). Making the choice an explicit mode is
// what keeps `submit` from silently dropping one of them — the old code took
// the path whenever it was non-empty, discarding any picked files without a
// word.
type ImportMode = 'upload' | 'path'

interface Props {
  open: boolean
  scope: Scope
  onClose: () => void
  onImported: (skill: Skill) => void
}

const BUNDLE_FORMAT = 'webui.skill.bundle.v1'

function sourceName(path: string): string {
  const normalized = path.trim().replace(/\/+$/, '')
  return normalized.split('/').filter(Boolean).pop() || normalized || 'skill'
}

function relativePath(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath
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

export function SkillsFromLocalModal({
  open,
  scope,
  onClose,
  onImported
}: Props) {
  const { t } = useT()
  const { message } = App.useApp()
  const [mode, setMode] = useState<ImportMode>('upload')
  const [picks, setPicks] = useState<LocalPick[]>([])
  const [localPath, setLocalPath] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [dragging, setDragging] = useState(false)
  const folderInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setMode('upload')
    setPicks([])
    setLocalPath('')
    setDragging(false)
  }, [open])

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

  const submit = async () => {
    if (!ready) return

    setSubmitting(true)
    try {
      if (mode === 'path') {
        onImported(
          await api.createSkill({
            name: sourceName(localPath.trim()),
            kind: 'source',
            content: localPath.trim(),
            enabled: true,
            scope
          })
        )
        return
      }
      // ONE SKILL PER FOLDER. Merging the picks into a single bundle (what this
      // did before) produced one skill named after the first folder, carrying
      // every folder's files — the backend picks the first SKILL.md it finds and
      // re-roots everything on that directory, so the rest arrived mangled.
      let last: Skill | null = null
      for (const pick of picks) {
        last = await api.createSkill({
          name: pick.name,
          kind: 'bundle',
          content: await bundleContent(pick.files),
          enabled: true,
          scope
        })
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
    setPicks((prev) => [
      ...prev,
      {
        uid: `${name}-${Date.now()}-${files.length}`,
        name,
        files
      }
    ])
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
      <Segmented<ImportMode>
        value={mode}
        onChange={setMode}
        options={[
          { value: 'upload', label: t.skillImport.localModeUpload },
          { value: 'path', label: t.skillImport.localModePath }
        ]}
        className="mb-2"
      />
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
                  <FolderIcon className="h-4 w-4" />
                  <span className="flex-1 truncate text-msa-text-1">
                    {pick.name}
                  </span>
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
