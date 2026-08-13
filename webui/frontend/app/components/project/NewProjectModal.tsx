import { App, Button, Form, Input, Modal, Radio, Tooltip } from 'antd'
import type { UploadFile } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api } from '~/lib/api'
import { dispatchWorkspaceChanged } from '~/lib/events'
import { collectDroppedFiles } from '~/lib/dropFiles'
import { useT } from '~/lib/i18n'
import type { MemoryBackend, Project } from '~/lib/types'
import UploadIcon from '~/assets/icons/upload.svg?react'
import {
  MEMORY_MODEL_DEFAULTS,
  MemoryModelConfig,
  memoryModelErrors,
  type MemoryModelErrors,
  type MemoryModelValue
} from './MemoryModelConfig'
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
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [memoryBackend, setMemoryBackend] = useState<MemoryBackend>('file')
  const [memoryModels, setMemoryModels] = useState<MemoryModelValue>(
    MEMORY_MODEL_DEFAULTS
  )
  // Invalid memory-model fields, set on a blocked submit and cleared the moment
  // the user edits the group (so the red state tracks the current input).
  const [memoryErrors, setMemoryErrors] = useState<MemoryModelErrors>({})
  // Editing a project whose memory was ever enabled: the backend is frozen.
  // Creating always starts unlocked — the lock is applied server-side the
  // moment the project is saved with memory on.
  const backendLocked = !!project?.memory_backend_locked
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
      setMemoryBackend(project.memory_backend ?? 'file')
      setMemoryModels({
        memory_llm_provider_id: project.memory_llm_provider_id ?? null,
        memory_llm_model: project.memory_llm_model ?? null,
        memory_embed_mode: project.memory_embed_mode ?? 'provider',
        memory_embed_provider_id: project.memory_embed_provider_id ?? null,
        memory_embed_model: project.memory_embed_model ?? null,
        memory_recall_top_k: project.memory_recall_top_k ?? null
      })
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
        setMemoryEnabled(s.default_memory_enabled)
        setMemoryBackend(s.default_memory_backend ?? 'file')
        setMemoryModels({
          memory_llm_provider_id: s.memory_llm_provider_id ?? null,
          memory_llm_model: s.memory_llm_model ?? null,
          memory_embed_mode: s.memory_embed_mode ?? 'provider',
          memory_embed_provider_id: s.memory_embed_provider_id ?? null,
          memory_embed_model: s.memory_embed_model ?? null,
          memory_recall_top_k: s.memory_recall_top_k ?? null
        })
        setFiles([])
        form.setFieldsValue({ name: '', instructions: '', local_path: '' })
      })
    }
  }, [open, project, form, isEditing])

  const submit = async () => {
    const v = await form.validateFields()
    // The memory-model group is not part of the antd Form, so validate it here.
    // Only guards the vector backend (the file backend has no such fields).
    if (memoryBackend === 'vector') {
      const errs = memoryModelErrors(memoryModels)
      if (Object.keys(errs).length > 0) {
        setMemoryErrors(errs)
        message.error(t.personalization.memoryModelIncomplete)
        return
      }
    }
    setSubmitting(true)
    try {
      if (isEditing) {
        // Update existing project
        const updated = await api.updateProject(project.id, {
          name: v.name,
          // local_path is deliberately not sent: it is read-only when editing
          // and the server rejects a change anyway.
          memory_enabled: memoryEnabled,
          // Omitted once locked: the server rejects a change, and re-sending
          // the current value would be a pointless round trip.
          ...(backendLocked ? {} : { memory_backend: memoryBackend }),
          // The memory-model group is project-owned; send it whole so the
          // server replaces the stored copy.
          ...(memoryBackend === 'vector' ? memoryModels : {})
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
          memory_backend: memoryBackend,
          ...(memoryBackend === 'vector' ? memoryModels : {})
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
          label={`${t.projects.nameLabel}`}
          name="name"
          rules={[{ required: true }]}
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
              // Folders are walked (see lib/dropFiles): `dataTransfer.files`
              // would report a dropped directory as one unreadable entry.
              const entries = await collectDroppedFiles(e.dataTransfer)
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

        {/* Project location. Read-only when editing: the directory IS the
            project's identity and holds all of its data, and nothing moves it on
            disk, so a changed path would point at a directory without the
            project's sessions/workspace/memory (the server rejects it too). */}
        <Form.Item
          label={t.newProject.locationLabel}
          name="local_path"
          className="!mb-0"
        >
          <Input
            placeholder={t.newProject.locationPlaceholder}
            readOnly={isEditing}
            disabled={isEditing}
          />
        </Form.Item>
        {/* Hint styled like the memory-backend one below rather than antd's
            `extra`, which renders at the body font size and sits flush against
            the field. */}
        <div className="mt-1.5 mb-6 text-xs text-msa-text-3">
          {isEditing
            ? t.newProject.locationLockedHint
            : t.newProject.locationHint}
        </div>

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

          {/* Storage backend — only meaningful with memory on, and frozen once
              the project has ever had memory enabled (it decides the on-disk
              layout, so switching later would orphan stored memory). */}
          <div className="mt-3 flex items-center gap-3">
            <span
              className={`text-sm ${
                memoryEnabled ? 'text-msa-text-2' : 'text-msa-text-disabled'
              }`}
            >
              {t.newProject.memoryBackendLabel}
            </span>
            {/* Disabled while memory is off (nothing to store, so the choice is
                meaningless) and once the backend is frozen.

                Keyed on the LIVE toggle above, never on the SAVED
                `project.memory_enabled`: the server only accepts a backend change
                while memory has NEVER been enabled
                (projects.py::_backend_locked), so gating on the saved value made
                the control unreachable exactly when it was still changeable.
                Flipping the switch here re-enables these instantly. */}
            <Radio.Group
              value={memoryBackend}
              disabled={backendLocked || !memoryEnabled}
              onChange={(e) => setMemoryBackend(e.target.value)}
            >
              <Radio value="file">{t.newProject.backendFile}</Radio>
              <Radio value="vector">{t.newProject.backendVector}</Radio>
            </Radio.Group>
          </div>
          <div className="mt-1.5 text-xs text-msa-text-3">
            {backendLocked
              ? t.newProject.memoryBackendLockedHint
              : t.newProject.memoryBackendHint}
          </div>

          {/* Vector-only extended config, owned by THIS project (the global
              settings only pre-filled it at open). */}
          {memoryBackend === 'vector' && (
            <div className="mt-4 border-t border-msa-line-1 pt-4">
              <MemoryModelConfig
                value={memoryModels}
                errors={memoryErrors}
                onChange={(patch) => {
                  setMemoryModels((cur) => ({ ...cur, ...patch }))
                  // Any edit invalidates the last submit's error flags.
                  setMemoryErrors({})
                }}
              />
              {isEditing &&
                backendLocked &&
                project?.memory_backend === 'vector' &&
                (memoryModels.memory_embed_mode !==
                  (project.memory_embed_mode ?? 'provider') ||
                  memoryModels.memory_embed_provider_id !==
                    (project.memory_embed_provider_id ?? null) ||
                  memoryModels.memory_embed_model !==
                    (project.memory_embed_model ?? null)) && (
                  <div className="mt-2 text-xs text-msa-text-danger">
                    {t.newProject.embedChangeWarn}
                  </div>
                )}
            </div>
          )}
        </div>
      </Form>
    </Modal>
  )
}
