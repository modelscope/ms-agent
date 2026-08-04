import { Button, Form, Input, Modal, Tooltip } from 'antd'
import type { UploadFile } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api } from '~/lib/api'
import { dispatchWorkspaceChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import type { AgentSettings, Project } from '~/lib/types'
import UploadIcon from '~/assets/icons/upload.svg?react'
import { MsaSwitch } from '../common/MsaSwitch'
import { MsaButton } from '../common/MsaButton'
import CloseIcon from '~/assets/icons/close.svg?react'
import { FileTypeIcon } from '~/components/common/FileCard'

interface Props {
  open: boolean
  project?: Project
  onClose: () => void
  onCreated: (project: Project) => void
  onUpdated?: (project: Project) => void
}

interface FormValues {
  name: string
  instructions: string
  local_path: string
}

export function NewProjectModal({
  open,
  project,
  onClose,
  onCreated,
  onUpdated
}: Props) {
  const { t } = useT()
  const [form] = Form.useForm<FormValues>()
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [files, setFiles] = useState<UploadFile[]>([])
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  // Callback ref: set webkitdirectory the moment the input appears in the DOM
  // (antd Modal renders content lazily via portal, so a one-time useEffect on
  // mount misses the timing).
  const folderRef = (el: HTMLInputElement | null) => {
    folderInputRef.current = el
    if (el) {
      el.setAttribute('webkitdirectory', '')
      el.setAttribute('directory', '')
    }
  }

  const isEditing = !!project

  useEffect(() => {
    if (!open) return
    if (isEditing) {
      // Edit mode: load existing project data
      setMemoryEnabled(project.memory_enabled ?? true)
      setFiles([])
      form.setFieldsValue({
        name: project.name,
        instructions: '',
        local_path: project.local_path ?? ''
      })
      // Load existing instruction
      api
        .getInstruction(`project:${project.id}`)
        .then((ins) => {
          form.setFieldsValue({ instructions: ins.content ?? '' })
        })
        .catch(() => {
          // No instruction saved yet
        })
    } else {
      // Create mode: reset form with default settings
      api.getAgentSettings().then((s) => {
        setSettings(s)
        setMemoryEnabled(s.default_memory_enabled)
        setFiles([])
        form.setFieldsValue({ name: '', instructions: '', local_path: '' })
      })
    }
  }, [open, project, form, isEditing])

  const submit = async () => {
    const v = await form.validateFields()
    setSubmitting(true)
    try {
      if (isEditing) {
        // Update existing project
        const updated = await api.updateProject(project.id, {
          name: v.name,
          local_path: v.local_path,
          memory_enabled: memoryEnabled
        })
        await api.putInstruction(`project:${project.id}`, v.instructions.trim())
        if (files.length > 0) {
          const uploads = files
            .filter((f) => f.originFileObj)
            .map((f) =>
              api
                .uploadWorkspaceFile(
                  project.id,
                  f.originFileObj!,
                  f.originFileObj!.webkitRelativePath || f.name
                )
                .catch(() => {})
            )
          await Promise.all(uploads)
          dispatchWorkspaceChanged()
        }
        form.resetFields()
        onUpdated?.(updated)
      } else {
        // Create new project
        const created = await api.createProject({
          name: v.name,
          local_path: v.local_path,
          memory_enabled: memoryEnabled,
          memory_backend: settings?.default_memory_backend ?? 'file'
        })
        if (v.instructions.trim()) {
          await api.putInstruction(`project:${created.id}`, v.instructions)
        }
        if (files.length > 0) {
          const uploads = files
            .filter((f) => f.originFileObj)
            .map((f) =>
              api
                .uploadWorkspaceFile(
                  created.id,
                  f.originFileObj!,
                  f.originFileObj!.webkitRelativePath || f.name
                )
                .catch(() => {})
            )
          await Promise.all(uploads)
          dispatchWorkspaceChanged()
        }
        form.resetFields()
        onCreated(created)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      title={isEditing ? t.projects.editTitle : t.projects.createTitle}
      onCancel={onClose}
      onOk={submit}
      okText={isEditing ? t.projects.save : t.projects.create}
      cancelText={t.projects.cancel}
      confirmLoading={submitting}
      destroyOnHidden
      width={520}
    >
      <Form form={form} layout="vertical" className="!mt-4">
        <Form.Item
          label={`${t.projects.nameLabel}：`}
          name="name"
          rules={[{ required: true, message: '' }]}
        >
          <Input placeholder={t.projects.namePlaceholder} autoFocus />
        </Form.Item>

        <Form.Item label={t.newProject.instructionsLabel} name="instructions">
          <Input.TextArea
            rows={3}
            placeholder={t.newProject.instructionsPlaceholder}
            classNames={{ textarea: 'resize-none' }}
          />
        </Form.Item>

        <Form.Item label={t.newProject.addFilesLabel}>
          {/* Unified drop zone: accepts file & folder drops + two pick buttons */}
          <div
            className="flex cursor-pointer flex-col items-center gap-3 rounded-lg border border-dashed border-msa-line-2 bg-msa-fill-1 px-4 py-8 transition-colors hover:border-msa-purple-5"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'copy'
            }}
            onDrop={async (e) => {
              e.preventDefault()
              e.stopPropagation()
              // Use the FileSystem API to traverse dropped folders and extract
              // individual files with their relative paths preserved.
              const entries: { file: File; path: string }[] = []
              const readEntry = async (
                entry: FileSystemEntry,
                basePath: string
              ) => {
                if (entry.isFile) {
                  const file = await new Promise<File>((resolve) =>
                    (entry as FileSystemFileEntry).file(resolve)
                  )
                  entries.push({ file, path: basePath + file.name })
                } else if (entry.isDirectory) {
                  const reader = (
                    entry as FileSystemDirectoryEntry
                  ).createReader()
                  let batch: FileSystemEntry[] = []
                  // readEntries is chunked; loop until empty.
                  do {
                    batch = await new Promise<FileSystemEntry[]>((resolve) =>
                      reader.readEntries(resolve)
                    )
                    for (const child of batch)
                      await readEntry(child, basePath + entry.name + '/')
                  } while (batch.length > 0)
                }
              }
              const items = Array.from(e.dataTransfer.items)
              for (const item of items) {
                if (item.kind !== 'file') continue
                const entry = item.webkitGetAsEntry?.()
                if (entry) {
                  await readEntry(entry, '')
                } else {
                  const f = item.getAsFile()
                  if (f) entries.push({ file: f, path: f.name })
                }
              }
              if (entries.length === 0) return
              const dropped = entries.map(({ file, path }) => ({
                uid: `${path}-${file.lastModified}-${Math.random()}`,
                name: path,
                size: file.size,
                status: 'done' as const,
                originFileObj: file
              }))
              setFiles((prev) => [...prev, ...(dropped as UploadFile[])])
            }}
          >
            <UploadIcon className="h-8 w-8 text-msa-text-3" />
            <p className="m-0 text-xs text-msa-text-3">
              {t.newProject.dropZoneTip}
            </p>
            <div className="flex gap-3" onClick={(e) => e.stopPropagation()}>
              <MsaButton
                size="small"
                variant="primary"
                onClick={() => fileInputRef.current?.click()}
              >
                {t.workspace.uploadFile}
              </MsaButton>
              <MsaButton
                size="small"
                variant="primary"
                onClick={() => folderInputRef.current?.click()}
              >
                {t.workspace.uploadFolder}
              </MsaButton>
            </div>
          </div>
          {/* Hidden file inputs */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (!e.target.files) return
              const selected = Array.from(e.target.files).map(
                (file) =>
                  ({
                    uid: `${file.name}-${file.lastModified}-${Math.random()}`,
                    name: file.webkitRelativePath || file.name,
                    size: file.size,
                    status: 'done',
                    originFileObj: file
                  }) as UploadFile
              )
              setFiles((prev) => [...prev, ...selected])
              e.target.value = ''
            }}
          />
          <input
            ref={folderRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              if (!e.target.files) return
              const selected = Array.from(e.target.files).map(
                (file) =>
                  ({
                    uid: `${file.name}-${file.lastModified}-${Math.random()}`,
                    name: file.webkitRelativePath || file.name,
                    size: file.size,
                    status: 'done',
                    originFileObj: file
                  }) as UploadFile
              )
              setFiles((prev) => [...prev, ...selected])
              e.target.value = ''
            }}
          />
          {files.length > 0 && (
            <div className="mt-2 max-h-[200px] space-y-1 overflow-y-auto">
              {files.map((f) => (
                <div
                  key={f.uid}
                  className="flex items-center gap-2 rounded-lg border border-msa-line-1 bg-msa-fill-1 px-3 py-2 text-xs"
                >
                  <FileTypeIcon name={f.name} className="h-4 w-4" />
                  <span className="flex-1 truncate text-msa-text-1">
                    {f.name}
                  </span>
                  <Tooltip title={t.resources.remove}>
                    <Button
                      type="text"
                      size="small"
                      icon={<CloseIcon className="h-3.5 w-3.5" />}
                      onClick={() =>
                        setFiles((prev) => prev.filter((x) => x.uid !== f.uid))
                      }
                    />
                  </Tooltip>
                </div>
              ))}
            </div>
          )}
        </Form.Item>

        <Form.Item label={t.newProject.locationLabel} name="local_path">
          <Input placeholder={t.newProject.locationPlaceholder} />
        </Form.Item>

        {/* Memory toggle section */}
        <div className="mb-2">
          <div className="text-sm font-medium text-msa-text-1 mb-2">
            {t.newProject.memoryTitle}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-msa-text-2">
              {t.newProject.memoryDesc}
            </span>
            <MsaSwitch checked={memoryEnabled} onChange={setMemoryEnabled} />
          </div>
        </div>
      </Form>
    </Modal>
  )
}
