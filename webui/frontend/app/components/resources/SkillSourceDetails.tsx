import { Checkbox } from 'antd'
import { useT } from '~/lib/i18n'
import type { SkillPlan, SkillSource } from '~/lib/types'

export function SkillSourceDetails({ source }: { source: SkillSource }) {
  const { t } = useT()
  const s = t.skillManagement
  return (
    <details className="mt-5 text-xs text-msa-text-3">
      <summary className="cursor-pointer py-2">{s.sourceDetails}</summary>
      <dl className="mt-2 grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-2">
        <dt>{s.source}</dt>
        <dd className="break-all text-msa-text-2">
          <a href={source.url} target="_blank" rel="noreferrer">
            {source.repository}
          </a>
        </dd>
        <dt>{s.directory}</dt>
        <dd className="break-all text-msa-text-2">{source.subdir || '/'}</dd>
        <dt>{source.selector_kind === 'branch' ? s.branch : s.fixedVersion}</dt>
        <dd className="break-all text-msa-text-2">{source.ref}</dd>
        <dt>{s.commit}</dt>
        <dd className="break-all font-mono text-msa-text-2">
          {source.revision.slice(0, 12)}
        </dd>
      </dl>
    </details>
  )
}

export function requiresSkillReview(plan: SkillPlan | null) {
  return (
    plan?.items.some((item) =>
      ['warning', 'dangerous'].includes(item.safety?.risk_level ?? '')
    ) ?? false
  )
}

export function SkillSafetyReview({
  plan,
  checked,
  onChange
}: {
  plan: SkillPlan
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  const { t } = useT()
  if (!requiresSkillReview(plan)) return null
  return (
    <div className="mt-4 rounded-lg border border-msa-line-1 bg-msa-fill-2 p-3 text-sm">
      <details>
        <summary className="cursor-pointer font-medium text-msa-text-1">
          {t.skillManagement.safetyReview}
        </summary>
        <div className="max-h-40 overflow-auto">
          {plan.items
            .filter((item) => item.safety?.findings.length)
            .map((item) => (
              <div key={item.id} className="mt-3 text-xs text-msa-text-2">
                <p className="font-medium">{item.name}</p>
                {item.safety?.findings.map((finding, i) => (
                  <div key={i} className="mt-2 break-words">
                    <p>{finding.description}</p>
                    <code className="whitespace-pre-wrap break-all text-msa-text-3">
                      {finding.evidence}
                    </code>
                  </div>
                ))}
              </div>
            ))}
        </div>
      </details>
      <Checkbox
        className="mt-3"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      >
        {t.skillManagement.safetyConsent}
      </Checkbox>
    </div>
  )
}
