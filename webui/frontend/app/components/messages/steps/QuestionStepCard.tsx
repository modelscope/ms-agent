import { Tooltip } from 'antd'
import { IconButton } from '~/components/common/IconButton'
import { ScrollArea } from '~/components/common/ScrollArea'
import { useEffect, useMemo, useRef, useState } from 'react'
import { MsaButton } from '~/components/common/MsaButton'
import { MsaTextArea } from '~/components/common/MsaTextArea'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import { useCollapseTransition } from '../useCollapseTransition'
import type { AgentStep } from '~/lib/agentProvider'
import {
  CUSTOM_OPTION_ID,
  allAnswered,
  answerLabels,
  createQuestionState,
  editCustom,
  isAnswered,
  select,
  setTab,
  syncQuestionState,
  toAnswers
} from '../questionState'
import type { QuestionState, QuestionView } from '../questionState'
import AskIcon from '~/assets/icons/custom-instruction.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'
import TaskDoneIcon from '~/assets/icons/task-done.svg?react'
import EditIcon from '~/assets/icons/edit.svg?react'

type AskState =
  | 'pending'
  | 'answered'
  | 'skipped'
  | 'cancelled'
  | 'timeout'
  | 'unavailable'
  | 'closed'

interface AnswerRecord {
  question_id?: string
  labels?: string[]
}

/** 逐题选择与输入，统一提交；回答后在原卡片显示完整问答摘要。 */
export function QuestionStepCard({
  step,
  isLast
}: {
  step: AgentStep
  /** Expanded while it's the message's last part; auto-collapses after. */
  isLast?: boolean
}) {
  const { t } = useT()
  const metaState = (step.meta.state as AskState) ?? 'pending'
  const [localState, setLocalState] = useState<AskState | null>(null)
  const state = metaState !== 'pending' ? metaState : localState ?? metaState
  const inFlight = useRef(false)

  const questions = useMemo<QuestionView[]>(() => {
    const raw = step.meta.questions
    return Array.isArray(raw) ? (raw as QuestionView[]) : []
  }, [step.meta.questions])

  const [qs, setQs] = useState<QuestionState>(() =>
    createQuestionState(questions.length)
  )
  useEffect(() => {
    setQs((prev) => syncQuestionState(prev, questions.length))
  }, [questions.length])

  const pending = state === 'pending'
  const [expanded, setExpanded] = useState(pending || state === 'answered')
  const { animating, onTransitionEnd } = useCollapseTransition(expanded)

  useEffect(() => {
    if (state === 'answered') setExpanded(true)
    else if (!isLast && !pending) setExpanded(false)
  }, [isLast, pending, state])

  const requestId = String(step.meta.request_id ?? '')
  const sessionId = String(step.meta.session_id ?? '')
  const live = pending && !!requestId && !!sessionId

  const submit = async (
    next: 'answered' | 'skipped',
    body: Parameters<typeof api.answerQuestion>[0]
  ) => {
    if (!live || inFlight.current) return
    inFlight.current = true
    setQs((prev) => ({ ...prev, submitting: true }))
    try {
      const { resolved } = await api.answerQuestion(body)
      // 过期或已被其他标签页回答不能推断为「取消」；服务端结局优先。
      setLocalState(resolved ? next : 'closed')
    } catch {
      // 网络失败保留输入，允许重试。
    } finally {
      inFlight.current = false
      setQs((prev) => ({ ...prev, submitting: false }))
    }
  }

  const onSubmit = () =>
    submit('answered', {
      session_id: sessionId,
      request_id: requestId,
      status: 'answered',
      answers: toAnswers(qs, questions)
    })

  const onSkip = () =>
    submit('skipped', {
      session_id: sessionId,
      request_id: requestId,
      status: 'skipped',
      answers: []
    })

  const onSelect = (optionId: string) =>
    setQs((prev) => select(prev, questions, optionId).state)

  const current = questions[qs.tab]
  const ready = allAnswered(qs, questions)
  const customSelected = (qs.picked[qs.tab] ?? []).includes(CUSTOM_OPTION_ID)
  const customValue = qs.custom[qs.tab] ?? ''
  const inputId = `question-${String(step.meta.call_id ?? requestId)}-${qs.tab}`
  const moveQuestion = (offset: number) =>
    setQs((prev) => setTab(prev, prev.tab + offset))
  const continueAnswering = () => {
    if (ready) void onSubmit()
    else moveQuestion(1)
  }

  return (
    <section data-question-card className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-1">
      <div className="flex items-center gap-2 px-3 py-2.5">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-none bg-transparent text-left text-sm font-medium text-msa-text-1"
        >
          <AskIcon className="h-4 w-4 shrink-0 text-msa-text-3" />
          <span>{state === 'answered' ? t.chat.questionAnswersTitle : t.chat.questionTitle}</span>
          {!pending && state !== 'answered' && (
            <span className="truncate text-xs font-normal text-msa-text-3">
              {outcomeNote(t, state, step, questions)}
            </span>
          )}
        </button>
        {live && questions.length > 1 && (
          <nav aria-label={t.chat.questionNavigator} className="flex shrink-0 items-center gap-1">
            <Tooltip title={t.chat.questionPrevious}>
              <IconButton
                size="sm"
                aria-label={t.chat.questionPrevious}
                disabled={qs.submitting || qs.tab === 0}
                onClick={() => moveQuestion(-1)}
                icon={<ArrowDownIcon className="h-3 w-3 rotate-90" />}
              />
            </Tooltip>
            <span aria-live="polite" className="min-w-10 text-center text-xs tabular-nums text-msa-text-3">
              {qs.tab + 1} / {questions.length}
            </span>
            <Tooltip title={t.chat.questionNext}>
              <IconButton
                size="sm"
                aria-label={t.chat.questionNext}
                disabled={qs.submitting || qs.tab === questions.length - 1}
                onClick={() => moveQuestion(1)}
                icon={<ArrowDownIcon className="h-3 w-3 -rotate-90" />}
              />
            </Tooltip>
          </nav>
        )}
        <Tooltip title={expanded ? t.chat.questionCollapse : t.chat.questionExpand}>
          <IconButton
            size="sm"
            aria-label={expanded ? t.chat.questionCollapse : t.chat.questionExpand}
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
            icon={<ArrowDownIcon className={`h-3 w-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />}
          />
        </Tooltip>
      </div>
      <div
        className={`grid duration-200 ease-in-out ${animating ? 'transition-[grid-template-rows]' : ''}`}
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
        onTransitionEnd={onTransitionEnd}
      >
        <div className="overflow-hidden">
          <ScrollArea pad={12} className="max-h-[min(26rem,55dvh)] py-2 space-y-4">
            {live && current ? (
              <div key={current.id} data-question-body className="space-y-3">
                <div className="flex items-start gap-2 text-sm font-semibold text-msa-text-1">
                  <span className="tabular-nums">{qs.tab + 1}.</span>
                  <span className="min-w-0 break-words">{current.question}</span>
                  {current.multi_select && (
                    <span className="shrink-0 rounded px-1.5 py-0.5 text-xs font-normal text-msa-text-3 bg-msa-fill-2">
                      {t.chat.questionMultiSelect}
                    </span>
                  )}
                </div>
                <div role={current.multi_select ? 'group' : 'radiogroup'} aria-label={current.question} className="space-y-1">
                  {current.options.map((option, index) => {
                    const picked = (qs.picked[qs.tab] ?? []).includes(option.id)
                    return (
                      <button
                        key={option.id}
                        type="button"
                        role={current.multi_select ? 'checkbox' : 'radio'}
                        aria-checked={picked}
                        disabled={qs.submitting}
                        onClick={() => onSelect(option.id)}
                        className={`flex w-full items-start gap-3 rounded-lg border px-2 py-2 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-msa-text-brand1 ${
                          picked ? 'border-msa-text-brand1 bg-msa-fill-2' : 'border-transparent bg-transparent hover:bg-msa-fill-2'
                        }`}
                      >
                        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded border text-xs font-medium ${
                          picked ? 'border-msa-text-brand1 text-msa-text-brand1' : 'border-msa-line-1 text-msa-text-3'
                        }`}>
                          {picked ? <TaskDoneIcon className="h-3.5 w-3.5" /> : String.fromCharCode(65 + index)}
                        </span>
                        <span className="min-w-0 flex-1 space-y-1 break-words">
                          <span className="block text-sm font-medium text-msa-text-1">{option.label}</span>
                          {option.description && <span className="block text-xs leading-relaxed text-msa-text-3">{option.description}</span>}
                        </span>
                      </button>
                    )
                  })}
                </div>
                {current.allow_custom !== false && (
                  <div className={`rounded-lg border p-2 space-y-1.5 ${customSelected ? 'border-msa-text-brand1 bg-msa-fill-2' : 'border-msa-line-1'}`}>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        role={current.multi_select ? 'checkbox' : 'radio'}
                        aria-label={t.chat.questionCustomOption}
                        aria-checked={customSelected}
                        disabled={qs.submitting}
                        onClick={() => onSelect(CUSTOM_OPTION_ID)}
                        className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded border border-msa-line-1 bg-transparent text-msa-text-3"
                      >
                        {customSelected ? <TaskDoneIcon className="h-4 w-4 text-msa-text-brand1" /> : <EditIcon className="h-4 w-4" />}
                      </button>
                      <label htmlFor={inputId} className="text-xs text-msa-text-3">{t.chat.questionCustomOption}</label>
                    </div>
                    <MsaTextArea
                      id={inputId}
                      maxLength={2000}
                      value={customValue}
                      disabled={qs.submitting}
                      placeholder={t.chat.questionCustomPlaceholder}
                      autoSize={{ minRows: 1, maxRows: 4 }}
                      onFocus={() => {
                        if (customValue.trim() && !customSelected)
                          setQs((prev) => editCustom(prev, prev.custom[prev.tab] ?? '', questions))
                      }}
                      onChange={(e) => setQs((prev) => editCustom(prev, e.target.value, questions))}
                    />
                    {customValue.trim() && (
                      <p role="status" className={`m-0 text-xs ${customSelected ? 'text-msa-text-brand1' : 'text-msa-text-3'}`}>
                        {customSelected ? t.chat.questionCustomSelected : t.chat.questionCustomRetained}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4" data-question-summary>
                {questions.map((q, i) => (
                  <div key={q.id} className="space-y-1 text-sm">
                    <p className="m-0 break-words font-medium text-msa-text-1">{q.question}</p>
                    <p className="m-0 whitespace-pre-wrap break-words text-msa-text-3">
                      {state === 'answered' ? resolvedLabels(step, qs, questions, i).join('、') || '—' : '—'}
                    </p>
                  </div>
                ))}
                {!questions.length && <p className="m-0 text-xs text-msa-text-3">{outcomeNote(t, state, step, questions)}</p>}
              </div>
            )}
          </ScrollArea>
          {live && current && (
            <div className="flex items-center justify-between gap-2 border-t border-msa-line-1 px-3 py-2">
              <span className="text-xs tabular-nums text-msa-text-3">
                {t.chat.questionAnsweredCount
                  .replace('{answered}', String(questions.filter((_, i) => isAnswered(qs, i)).length))
                  .replace('{total}', String(questions.length))}
              </span>
              <div className="flex items-center gap-2">
                <MsaButton variant="ghost" disabled={qs.submitting} onClick={onSkip}>{t.chat.questionSkip}</MsaButton>
                <MsaButton
                  variant="primary"
                  disabled={qs.submitting || (!ready && (!isAnswered(qs, qs.tab) || qs.tab === questions.length - 1))}
                  onClick={continueAnswering}
                >
                  {ready ? t.chat.questionSubmit : t.chat.questionContinue}
                </MsaButton>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

/**
 * Labels for question `index`, preferring what the SERVER said.
 *
 * The server's answers are authoritative because it recomputes labels from the
 * option ids; the local state is the fallback for the tab that just submitted,
 * whose outcome frame may not have arrived yet.
 */
function resolvedLabels(
  step: AgentStep,
  qs: QuestionState,
  questions: QuestionView[],
  index: number
): string[] {
  const raw = step.meta.answers
  if (Array.isArray(raw)) {
    const question = questions[index]
    const match = (raw as AnswerRecord[]).find(
      (a) => a?.question_id === question?.id
    )
    if (match?.labels?.length) return match.labels
  }
  return answerLabels(qs, questions, index)
}

/** One line saying how the ask ended, for the collapsed header. */
function outcomeNote(
  t: ReturnType<typeof useT>['t'],
  state: AskState,
  step: AgentStep,
  questions: QuestionView[]
): string {
  if (state === 'skipped') return t.chat.questionSkipped
  if (state === 'cancelled') return t.chat.questionCancelled
  if (state === 'timeout') return t.chat.questionTimedOut
  if (state === 'unavailable') return t.chat.questionUnavailable
  if (state === 'closed') return t.chat.questionClosed
  const raw = step.meta.answers
  if (Array.isArray(raw) && raw.length) {
    return (raw as AnswerRecord[])
      .map((a) => (a?.labels ?? []).join('、'))
      .filter(Boolean)
      .join(' · ')
  }
  return questions.length ? t.chat.questionAnswered : ''
}
