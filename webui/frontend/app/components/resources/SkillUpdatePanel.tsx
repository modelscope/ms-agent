import { App, Button, Spin } from 'antd'
import { MsaButton } from '~/components/common/MsaButton'
import { useEffect, useState } from 'react'
import { api } from '~/lib/api'
import { dispatchMcpSkillChanged } from '~/lib/events'
import { useT } from '~/lib/i18n'
import {
  isCancelled,
  SkillOperationError,
  skillErrorText,
  useSkillOperation
} from '~/lib/skillManagement'
import type { Skill, SkillDiff, SkillPlan } from '~/lib/types'
import {
  requiresSkillReview,
  SkillSafetyReview,
  SkillSourceDetails
} from './SkillSourceDetails'

export function SkillUpdatePanel({
  skill,
  kind,
  initialPlan,
  onRelink,
  onApplied,
  onCancel
}: {
  skill: Skill
  kind: 'update' | 'restore' | 'link'
  initialPlan?: SkillPlan | null
  onRelink?: () => void
  onApplied: () => void
  onCancel: () => void
}) {
  const { t } = useT()
  const s = t.skillManagement
  const { message } = App.useApp()
  const operation = useSkillOperation()
  const [plan, setPlan] = useState<SkillPlan | null>(null)
  const [selected, setSelected] = useState('')
  const [diff, setDiff] = useState<SkillDiff | null>(null)
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  const [error, setError] = useState('')

  async function prepare() {
    setLoading(true)
    setError('')
    setPlan(null)
    setDiff(null)
    setReviewed(false)
    try {
      if (kind === 'link' && !initialPlan) return
      const next =
        kind === 'link'
          ? initialPlan!
          : await operation.run(() => api.prepareSkillUpdate(skill.id, kind))
      setPlan(next)
      const files = next.items[0]?.changes ?? []
      setSelected(files.find((f) => !f.binary)?.path ?? files[0]?.path ?? '')
    } catch (e) {
      if (!isCancelled(e)) setError(skillErrorText(e, s))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    prepare()
  }, [skill.id, kind, initialPlan?.id])

  useEffect(() => {
    if (!plan || !selected) return
    let disposed = false
    setDiff(null)
    api
      .skillPlanDiff(plan.id, plan.items[0].id, selected)
      .then((value) => {
        if (!disposed) setDiff(value)
      })
      .catch((e) => {
        if (!disposed) setError(skillErrorText(e, s))
      })
    return () => {
      disposed = true
    }
  }, [plan, selected])

  async function apply() {
    if (!plan || applying) return
    setApplying(true)
    setError('')
    try {
      const results = await operation.run(() =>
        api.applySkillPlan(
          plan.id,
          crypto.randomUUID(),
          plan.items[0].local_status === 'clean' ? 'abort' : 'replace',
          reviewed
        )
      )
      const failed = results.find((r) => r.status === 'failed')
      if (failed)
        throw new SkillOperationError(
          failed.error ?? { code: 'OPERATION_FAILED', message: '' }
        )
      message.success(
        kind === 'link' ? s.linked : kind === 'restore' ? s.restored : s.updated
      )
      dispatchMcpSkillChanged()
      onApplied()
    } catch (e) {
      if (!isCancelled(e)) setError(skillErrorText(e, s))
    } finally {
      setApplying(false)
    }
  }

  const item = plan?.items[0]
  const modified = item && item.local_status !== 'clean'
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto px-5 py-5 sm:px-7">
        {item && (
          <p className="mb-4 break-all text-xs text-msa-text-3">
            {item.source.provider === 'github' ? 'GitHub' : 'ModelScope'} ·{' '}
            {item.source.repository}
          </p>
        )}
        {kind === 'restore' && skill.installation?.backup_at && (
          <p className="mb-4 text-xs text-msa-text-3">
            {s.restoreTarget.replace(
              '{date}',
              new Date(skill.installation.backup_at).toLocaleString()
            )}
          </p>
        )}
        {loading ? (
          <div className="flex justify-center py-12">
            <Spin aria-label={s.loading} />
          </div>
        ) : (
          item && (
            <>
              {item.previous_version && item.version_label && (
                <p className="mb-5 text-base text-msa-text-1">
                  {item.previous_version}{' '}
                  <span className="px-2 text-msa-text-3">→</span>{' '}
                  {item.version_label}
                </p>
              )}
              <p className="mb-3 text-sm text-msa-text-1">
                {item.changes.length
                  ? s.changedFiles.replace(
                      '{count}',
                      String(item.changes.length)
                    )
                  : s.noChanges}
              </p>
              <div className="mb-4 flex flex-col gap-1">
                {item.changes.map((file) => (
                  <button
                    key={file.path}
                    type="button"
                    aria-pressed={selected === file.path}
                    onClick={() => setSelected(file.path)}
                    className={`flex min-w-0 cursor-pointer items-center justify-between gap-3 rounded-md border-0 px-3 py-2 text-left text-xs transition-colors hover:bg-msa-fill-3 ${selected === file.path ? 'bg-msa-fill-2' : 'bg-transparent'}`}
                  >
                    <span className="break-all font-mono text-msa-text-2">
                      {file.path}
                    </span>
                    <span className="shrink-0 text-msa-text-3">
                      {file.kind === 'added'
                        ? s.added
                        : file.kind === 'removed'
                          ? s.removed
                          : s.changed}
                    </span>
                  </button>
                ))}
              </div>
              {selected &&
                (diff ? (
                  <div className="overflow-hidden rounded-lg border border-msa-line-1">
                    <div className="break-all bg-msa-fill-2 px-3 py-2 font-mono text-xs text-msa-text-2">
                      {selected}
                    </div>
                    {diff.binary ? (
                      <p className="p-4 text-xs text-msa-text-3">{s.binary}</p>
                    ) : (
                      <pre className="max-h-[42vh] overflow-auto py-2 text-xs leading-6">
                        {diff.diff?.split('\n').map((line, i) => (
                          <span
                            key={i}
                            className={`block min-w-max whitespace-pre px-3 ${line.startsWith('+') && !line.startsWith('+++') ? 'bg-msa-fill-green text-msa-green-8 dark:text-msa-green-3' : line.startsWith('-') && !line.startsWith('---') ? 'bg-msa-fill-error text-msa-text-1' : 'text-msa-text-2'}`}
                          >
                            {line || ' '}
                          </span>
                        ))}
                      </pre>
                    )}
                    {diff.truncated && (
                      <p className="px-3 py-2 text-xs text-msa-text-3">
                        {s.truncated}
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="py-8 text-center">
                    <Spin size="small" />
                  </div>
                ))}
              {modified && (
                <p className="mt-5 border-l-2 border-msa-line-2 pl-3 text-sm text-msa-text-2">
                  {item.local_status === 'unknown'
                    ? s.unknownBaseline
                    : s.overwriteNotice}
                </p>
              )}
              {plan && (
                <SkillSafetyReview
                  plan={plan}
                  checked={reviewed}
                  onChange={setReviewed}
                />
              )}
              <SkillSourceDetails source={item.source} />
            </>
          )
        )}
        {error && (
          <div
            role="alert"
            className="mt-4 flex flex-wrap items-center gap-3 text-sm text-msa-deco-red"
          >
            <span>{error}</span>
            <Button
              size="small"
              onClick={kind === 'link' ? onRelink : prepare}
              disabled={applying}
            >
              {s.retry}
            </Button>
          </div>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-msa-line-1 px-5 py-4">
        <Button
          onClick={async () => {
            await operation.cancel()
            onCancel()
          }}
        >
          {s.cancel}
        </Button>
        <MsaButton
          variant="primary"
          loading={applying}
          disabled={
            !item ||
            loading ||
            (kind === 'update' && !item.changes.length && !modified) ||
            (requiresSkillReview(plan) && !reviewed)
          }
          onClick={apply}
        >
          {kind === 'link'
            ? modified
              ? s.replaceAndLink
              : s.linkSource
            : kind === 'restore'
              ? modified
                ? s.overwriteRestore
                : s.restore
              : modified
                ? s.overwriteUpdate
                : s.update}
        </MsaButton>
      </div>
    </div>
  )
}
