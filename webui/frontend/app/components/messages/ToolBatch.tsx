import { useEffect, useState } from 'react'
import { useT } from '~/lib/i18n'
import type { AgentPart } from '~/lib/agentProvider'
import { StepCard } from './StepCard'
import type { OnOpenStep, OnOpenFile } from './types'
import TodoIcon from '~/assets/icons/todo.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'

type StepPart = Extract<AgentPart, { kind: 'step' }>

/**
 * Outer accordion wrapping one server tool-call round (1..N consecutive tool
 * steps): header reads "used N tools", the body holds the individual step
 * cards (their own UI/accordions unchanged).
 *
 * Expansion mirrors the ThoughtsFlow convention: open while it's the
 * message's LAST meaningful block (the in-flight round streams visibly),
 * auto-collapses once newer parts arrive; a pending authorization inside
 * pins it open (the approve/reject buttons must stay reachable).
 */
export function ToolBatch({
  steps,
  isLast,
  onOpenStep,
  onOpenFile
}: {
  steps: StepPart[]
  isLast: boolean
  onOpenStep?: OnOpenStep
  onOpenFile?: OnOpenFile
}) {
  const { t } = useT()
  const hasPending = steps.some(
    (p) => String(p.step.meta.state ?? '') === 'pending'
  )
  const [expanded, setExpanded] = useState(isLast || hasPending)

  useEffect(() => {
    if (!isLast && !hasPending) setExpanded(false)
  }, [isLast, hasPending])

  return (
    <div>
      <div
        onClick={() => setExpanded((v) => !v)}
        className="flex cursor-pointer items-center gap-1.5 text-sm font-medium text-msa-text-2"
      >
        <TodoIcon className="h-5 w-5 shrink-0" />
        <span>{t.chat.useTools.replace('{n}', String(steps.length))}</span>
        <ArrowDownIcon
          className={`h-3 w-3 transition-transform duration-200 ${
            expanded ? 'rotate-180' : ''
          }`}
        />
      </div>
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-in-out"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="space-y-3 pt-3">
            {steps.map((p, i) => (
              <StepCard
                key={i}
                step={p.step}
                onOpenStep={onOpenStep}
                onOpenFile={onOpenFile}
                // Inner accordions keep their own live-expansion rule: only
                // the round's newest card counts as "last".
                isLast={isLast && i === steps.length - 1}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
