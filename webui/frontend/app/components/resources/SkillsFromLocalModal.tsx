import { Button, Input, Modal, Upload, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { MsaButton } from '~/components/common/MsaButton'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Scope, Skill } from '~/lib/types'
import UploadIcon from '~/assets/icons/upload.svg?react'
import CloseIcon from '~/assets/icons/close.svg?react'
import FolderIcon from '~/assets/icons/folder.svg?react'
import { FileTypeIcon } from '~/components/common/FileCard'

type LocalPick =
  | { kind: 'file'; uid: string; name: string; size: number; files: File[] }
  | { kind: 'dir'; uid: string; name: string; fileCount: number; files: File[] }

interface Props {
  open: boolean
  scope: Scope
  onClose: () => void
  onImported: (skill: Skill) => void
}

const BUNDLE_FORMAT = 'webui.skill.bundle.v1'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function sourceName(path: string): string {
  const normalized = path.trim().replace(/\/+$/, '')
  return normalized.split('/').filter(Boolean).pop() || normalized || 'skill'
}

function relativePath(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath
  return rel || file.name
}

async function bundleContent(files: File[]): Promise<string> {
  const payloadFiles = await Promise.all(
    files.map(async (file) => ({
      path: relativePath(file),
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
  const [picks, setPicks] = useState<LocalPick[]>([])
  const [localPath, setLocalPath] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const folderInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setPicks([])
    setLocalPath('')
  }, [open])

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
    const path = localPath.trim()
    if (!path && picks.length === 0) {
      onClose()
      return
    }

    setSubmitting(true)
    try {
      const skill = path
        ? await api.createSkill({
            name: sourceName(path),
            kind: 'source',
            content: path,
            enabled: true,
            scope
          })
        : await api.createSkill({
            name: picks[0]?.name ?? 'skill',
            kind: 'bundle',
            content: await bundleContent(picks.flatMap((pick) => pick.files)),
            enabled: true,
            scope
          })
      onImported(skill)
    } catch {
      // API errors surface via the global toast (see root ApiErrorBridge).
    } finally {
      setSubmitting(false)
    }
  }

  const addFile = (file: File) => {
    setPicks((prev) => [
      ...prev,
      {
        kind: 'file',
        uid: `${file.name}-${file.lastModified}-${file.size}`,
        name: file.name,
        size: file.size,
        files: [file]
      }
    ])
  }

  const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length === 0) return
    const rel = relativePath(files[0])
    const dirName = rel.includes('/') ? rel.split('/')[0] : 'folder'
    setPicks((prev) => [
      ...prev,
      {
        kind: 'dir',
        uid: `${dirName}-${Date.now()}`,
        name: dirName,
        fileCount: files.length,
        files
      }
    ])
    e.target.value = ''
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
      okButtonProps={{ loading: submitting }}
      destroyOnHidden
      width={560}
    >
      <Upload.Dragger
        multiple
        showUploadList={false}
        openFileDialogOnClick={false}
        beforeUpload={(file) => {
          addFile(file)
          return false
        }}
        className="bg-msa-fill-1 border-msa-line-1"
      >
        <p className="m-0">
          <UploadIcon className="h-[32px] w-[32px] text-msa-text-brand1" />
        </p>
        <p className="m-0 my-2 text-sm text-msa-text-2">
          {t.skillImport.localDropHint}
        </p>
        <div className="flex items-center justify-center gap-3">
          <Upload
            multiple
            showUploadList={false}
            beforeUpload={(file) => {
              addFile(file)
              return false
            }}
          >
            <MsaButton variant="primary">
              {t.skillImport.localPickFile}
            </MsaButton>
          </Upload>
          <MsaButton
            variant="primary"
            onClick={(e) => {
              e.stopPropagation()
              folderInputRef.current?.click()
            }}
          >
            {t.skillImport.localPickFolder}
          </MsaButton>
        </div>
      </Upload.Dragger>

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
              {/* Project's own file badge / folder glyph (same as the
                  workspace tree) instead of generic doc icons. */}
              {pick.kind === 'file' ? (
                <FileTypeIcon name={pick.name} className="h-4 w-4" />
              ) : (
                <FolderIcon className="h-4 w-4" />
              )}
              <span className="flex-1 truncate text-msa-text-1">
                {pick.name}
              </span>
              <span className="shrink-0 text-msa-text-3">
                {pick.kind === 'file'
                  ? formatSize(pick.size)
                  : `${pick.fileCount} ${t.skillImport.localFolderFiles}`}
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

      <div className="mt-4">
        <Input
          value={localPath}
          onChange={(e) => setLocalPath(e.target.value)}
          placeholder={t.skillImport.localPathPlaceholder}
        />
        <Typography.Paragraph className="!mt-1 !mb-3 !text-xs !text-msa-text-3">
          {t.skillImport.localPathHint}
        </Typography.Paragraph>
      </div>

      <div>
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
