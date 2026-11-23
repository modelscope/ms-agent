import { App, Button, Checkbox, Input, Modal, Radio, Select } from 'antd'
import { MsaButton } from '~/components/common/MsaButton'
import { useEffect, useRef, useState } from 'react'
import { api } from '~/lib/api'
import { dispatchMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import {
  isCancelled,
  SkillOperationError,
  skillErrorText,
  useSkillOperation
} from '~/lib/skillManagement'
import type {
  Scope,
  Skill,
  SkillItemResult,
  SkillOperation,
  SkillPlan,
  SkillSourcePreview
} from '~/lib/types'
import {
  requiresSkillReview,
  SkillSafetyReview,
  SkillSourceDetails
} from './SkillSourceDetails'

export function SkillsFromLinkModal({
  open,
  scope,
  onClose,
  onImported,
  linkSkill,
  onPrepared
}: {
  open: boolean
  scope: Scope
  onClose: () => void
  onImported: () => void
  linkSkill?: Skill
  onPrepared?: (plan: SkillPlan) => void
}) {
  const { t } = useT()
  const s = t.skillManagement
  const { message } = App.useApp()
  const operation = useSkillOperation()
  const [source, setSource] = useState('')
  const [target, setTarget] = useState<Scope>(scope)
  const [locations, setLocations] = useState<{ value: Scope; label: string }[]>(
    []
  )
  const [preview, setPreview] = useState<SkillSourcePreview | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [plan, setPlan] = useState<SkillPlan | null>(null)
  const [results, setResults] = useState<SkillItemResult[]>([])
  const [reviewed, setReviewed] = useState(false)
  const [phase, setPhase] = useState<
    'resolving' | 'preparing' | 'applying' | null
  >(null)
  const [applyStatus, setApplyStatus] = useState<
    SkillOperation['status'] | null
  >(null)
  const [error, setError] = useState('')
  const attempt = useRef(0)
  const busy = phase !== null

  useEffect(() => {
    attempt.current++
    if (!open) return
    setSource('')
    setTarget(scope)
    setPreview(null)
    setPlan(null)
    setSelected([])
    setResults([])
    setReviewed(false)
    setPhase(null)
    setApplyStatus(null)
    setError('')
    let disposed = false
    api
      .listProjects()
      .then((projects) => {
        if (!disposed)
          setLocations([
            { value: 'global', label: t.resources.globalSkills },
            ...projects.map((p) => ({
              value: `project:${p.id}` as Scope,
              label: p.name
            }))
          ])
      })
      .catch(() => {})
    return () => {
      disposed = true
      attempt.current++
    }
  }, [open, scope, linkSkill?.id])

  async function inspect() {
    if (!source.trim() || busy) return
    const current = ++attempt.current
    setPhase('resolving')
    setError('')
    try {
      const next = await operation.run(() =>
        api.inspectSkillSource(target, source.trim())
      )
      if (current !== attempt.current) return
      setPreview(next)
      setPlan(null)
      setResults([])
      setReviewed(false)
      setSelected(
        next.candidates.length === 1 &&
          !next.candidates[0].error &&
          (linkSkill || !next.candidates[0].conflict)
          ? [next.candidates[0].id]
          : []
      )
    } catch (e) {
      if (current === attempt.current && !isCancelled(e))
        setError(skillErrorText(e, s))
    } finally {
      if (current === attempt.current) setPhase(null)
    }
  }

  async function install() {
    if (!preview || !selected.length || busy) return
    const current = ++attempt.current
    setPhase('preparing')
    setError('')
    try {
      if (linkSkill) {
        const prepared = await operation.run(() =>
          api.prepareSkillLink(linkSkill.id, preview.id, selected[0])
        )
        if (current === attempt.current) onPrepared?.(prepared)
        return
      }
      const prepared =
        plan ??
        (await operation.run(() =>
          api.prepareSkillInstall(target, preview.id, selected)
        ))
      if (current !== attempt.current) return
      setPlan(prepared)
      if (requiresSkillReview(prepared) && !reviewed) return
      setPhase('applying')
      setApplyStatus('queued')
      setResults((previous) => previous.filter((r) => r.status === 'succeeded'))
      const applied = await operation.run(
        () =>
          api.applySkillPlan(prepared.id, crypto.randomUUID(), 'abort', reviewed),
        (progress) => {
          if (current !== attempt.current) return
          setApplyStatus(progress.status)
          if (progress.result) {
            // A retry reports earlier successes again before reaching the
            // failed item. Keep successes not yet replayed by this operation.
            const updates = progress.result
            setResults((previous) => {
              const merged = new Map(previous.map((r) => [r.item_id, r]))
              for (const result of updates) merged.set(result.item_id, result)
              return [...merged.values()]
            })
          }
        }
      )
      if (current !== attempt.current) return
      setResults(applied)
      const succeeded = applied.filter((r) => r.status === 'succeeded').length
      if (succeeded === applied.length) {
        message.success(
          succeeded > 1
            ? s.installedCount.replace('{count}', String(succeeded))
            : s.installed
        )
        onImported()
      } else {
        dispatchMcpSkillChanged()
        setError(
          s.partial
            .replace('{success}', String(succeeded))
            .replace('{failed}', String(applied.length - succeeded))
        )
      }
    } catch (e) {
      if (current === attempt.current && !isCancelled(e))
        setError(skillErrorText(e, s))
    } finally {
      if (current === attempt.current) setPhase(null)
    }
  }

  const selectable =
    preview?.candidates.filter((c) => !c.conflict && !c.error) ?? []
  const collection = preview && 'kind' in preview.source ? preview.source : null
  const selectedNames = new Set(
    preview?.candidates
      .filter((c) => selected.includes(c.id))
      .map((c) => c.runtime_skill_id)
  )
  const nameCounts = new Map<string, number>()
  for (const candidate of selectable) {
    const name = candidate.runtime_skill_id
    nameCounts.set(name, (nameCounts.get(name) ?? 0) + 1)
  }
  // Collections can contain alternatives with the same runtime name. Keep
  // that choice explicit; Select all includes unambiguous Skills only.
  const allCandidates = selectable.filter(
    (c) => nameCounts.get(c.runtime_skill_id) === 1 || selected.includes(c.id)
  )
  const completed = new Set(
    results.filter((r) => r.status === 'succeeded').map((r) => r.item_id)
  )
  const remaining = selected.filter((id) => !completed.has(id)).length
  const activeItem =
    phase === 'applying' && applyStatus === 'running'
      ? selected.find((id) => !results.some((r) => r.item_id === id))
      : undefined
  const choose = (ids: string[]) => {
    setSelected(ids)
    setPlan(null)
    setResults([])
    setReviewed(false)
  }
  const close = async () => {
    attempt.current++
    await operation.cancel()
    onClose()
  }

  return (
    <Modal
      open={open}
      title={linkSkill ? s.linkSource : s.fromLink}
      onCancel={close}
      destroyOnHidden
      width={560}
      styles={{
        body: {
          display: 'flex',
          flexDirection: 'column',
          maxHeight: 'calc(100dvh - 210px)',
          overflow: 'hidden'
        }
      }}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={close}>{s.cancel}</Button>
          <MsaButton
            variant="primary"
            loading={busy}
            disabled={
              preview
                ? !remaining || (requiresSkillReview(plan) && !reviewed)
                : !source.trim()
            }
            onClick={preview ? install : inspect}
          >
            {phase === 'applying'
              ? s.installing
              : preview && !linkSkill
                ? results.some((r) => r.status === 'failed')
                  ? s.retryFailed
                  : selected.length > 1
                    ? s.installCount.replace('{count}', String(remaining))
                    : s.install
                : s.continue}
          </MsaButton>
        </div>
      }
    >
      <div className="flex min-h-0 flex-col py-3">
        {preview ? (
          <div className="mb-4 flex shrink-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <a
                className="break-all text-sm text-msa-text-1"
                href={preview.source.url}
                target="_blank"
                rel="noreferrer"
              >
                {collection?.title ?? preview.source.repository}
              </a>
              <p className="mt-1 text-xs text-msa-text-3">
                {preview.source.provider === 'github' ? 'GitHub' : 'ModelScope'}
                {collection
                  ? ` · ${s.collection}`
                  : 'selector_kind' in preview.source &&
                      preview.source.selector_kind !== 'branch'
                    ? ` · ${s.fixedVersion}`
                    : ''}
              </p>
            </div>
            <Button
              type="text"
              disabled={busy}
              onClick={() => {
                setPreview(null)
                setPlan(null)
                setError('')
                setResults([])
              }}
            >
              {s.changeSource}
            </Button>
          </div>
        ) : (
          <label className="mb-5 block text-sm text-msa-text-1">
            {s.sourceLink}
            <Input
              className="mt-2"
              value={source}
              autoFocus
              disabled={busy}
              maxLength={2048}
              onChange={(e) => setSource(e.target.value)}
              onPressEnter={inspect}
              placeholder="https://github.com/…"
              aria-label={s.sourceLink}
            />
            <span className="mt-2 block text-xs text-msa-text-3">
              {s.sourceHint}
            </span>
          </label>
        )}
        <div className="mb-4 flex shrink-0 items-center gap-3">
          <label
            htmlFor="skill-install-scope"
            className="shrink-0 text-sm text-msa-text-2"
          >
            {s.installTo}
          </label>
          <Select
            id="skill-install-scope"
            value={target}
            disabled={!!linkSkill || busy || results.length > 0}
            className="min-w-0 flex-1"
            options={
              locations.length
                ? locations
                : [
                    {
                      value: scope,
                      label:
                        scope === 'global'
                          ? t.resources.globalSkills
                          : t.resources.projectSkills
                    }
                  ]
            }
            onChange={(value) => {
              setTarget(value)
              setPreview(null)
              setPlan(null)
              setError('')
            }}
          />
        </div>
        {preview && (
          <>
            {!linkSkill && (
              <Checkbox
                disabled={busy || results.length > 0 || !allCandidates.length}
                checked={
                  selected.length > 0 && selected.length === allCandidates.length
                }
                indeterminate={
                  selected.length > 0 && selected.length < allCandidates.length
                }
                onChange={(e) =>
                  choose(e.target.checked ? allCandidates.map((c) => c.id) : [])
                }
              >
                {s.selectAll}
              </Checkbox>
            )}
            <div className="mt-3 min-h-0 max-h-[42vh] overflow-auto">
              {preview.candidates.map((candidate) => {
                const result = results.find((r) => r.item_id === candidate.id)
                const duplicateSelected =
                  !selected.includes(candidate.id) &&
                  selectedNames.has(candidate.runtime_skill_id)
                const duplicateName =
                  (nameCounts.get(candidate.runtime_skill_id) ?? 0) > 1
                let status = ''
                if (result?.status === 'succeeded') status = s.installed
                else if (result?.status === 'failed') status = s.installFailed
                else if (candidate.error)
                  status = skillErrorText(
                    new SkillOperationError(candidate.error), s
                  )
                else if (candidate.conflict)
                  status = skillErrorText(
                    new SkillOperationError({ code: candidate.conflict, message: '' }),
                    s
                  )
                else if (phase === 'applying' && selected.includes(candidate.id))
                  status = activeItem === candidate.id ? s.installing : s.waiting
                else if (duplicateName) status = s.sameNameChoice
                return (
                  <div
                    key={candidate.id}
                    className="border-t border-msa-line-1 py-3"
                  >
                    <div className="flex items-start gap-3">
                      {linkSkill ? (
                        <Radio
                          id={`skill-candidate-${candidate.id}`}
                          aria-label={candidate.name}
                          className="mt-0.5"
                          checked={selected.includes(candidate.id)}
                          disabled={busy || !!candidate.error}
                          onChange={() => choose([candidate.id])}
                        />
                      ) : (
                        <Checkbox
                          id={`skill-candidate-${candidate.id}`}
                          aria-label={candidate.name}
                          className="mt-0.5"
                          checked={selected.includes(candidate.id)}
                          disabled={
                            busy || !!candidate.conflict || !!candidate.error ||
                            duplicateSelected || results.length > 0
                          }
                          onChange={(e) =>
                            choose(
                              e.target.checked
                                ? [...selected, candidate.id]
                                : selected.filter((id) => id !== candidate.id)
                            )
                          }
                        />
                      )}
                      <label
                        htmlFor={`skill-candidate-${candidate.id}`}
                        className="min-w-0 flex-1 cursor-pointer"
                      >
                        <span className="break-all text-sm text-msa-text-1">
                          {candidate.name}
                        </span>
                        {candidate.description !== candidate.name && (
                          <span
                            className="mt-1 line-clamp-2 text-xs leading-5 text-msa-text-3"
                            title={candidate.description}
                          >
                            {candidate.description}
                          </span>
                        )}
                        {preview.candidates.length > 1 && (
                          <span
                            className="mt-1 block truncate font-mono text-xs text-msa-text-3"
                            title={candidate.source_label ?? candidate.subdir}
                          >
                            {candidate.source_label ?? candidate.subdir}
                          </span>
                        )}
                      </label>
                      {(!linkSkill || candidate.error) && (
                        <span
                          aria-live="polite"
                          className="max-w-[35%] text-right text-xs text-msa-text-3"
                        >
                          {status}
                        </span>
                      )}
                    </div>
                    {result?.error && (
                      <p
                        role="alert"
                        className="mt-2 text-xs text-msa-deco-red"
                      >
                        {skillErrorText(
                          new SkillOperationError(result.error),
                          s
                        )}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
            {'revision' in preview.source && (
              <SkillSourceDetails source={preview.source} />
            )}
          </>
        )}
        {plan && (
          <SkillSafetyReview
            plan={plan}
            checked={reviewed}
            onChange={setReviewed}
          />
        )}
        {error && (
          <p role="alert" className="mt-4 text-sm text-msa-deco-red">
            {error}
          </p>
        )}
      </div>
    </Modal>
  )
}
