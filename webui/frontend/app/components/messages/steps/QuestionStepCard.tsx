import { Typography } from 'antd'
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
  cancelCustom,
  createQuestionState,
  editCustom,
  isAnswered,
  saveCustom,
  select,
  setTab,
  syncQuestionState,
  toAnswers
} from '../questionState'
import type { QuestionState, QuestionView } from '../questionState'
import AskIcon from '~/assets/icons/custom-instruction.svg?react'
import ArrowDownIcon from '~/assets/icons/arrow-down.svg?react'
import TaskDoneIcon from '~/assets/icons/task-done.svg?react'

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

/**
 * The card the model asks through: one tab per question, options as rows, a
 * "type your own" row, and Submit / Skip.
 *
 * Pending is the only interactive state and it stays EXPANDED — a turn cannot
 * advance until this is answered, so collapsing it would hide the one control
 * that unblocks the conversation. Every terminal state collapses to a one-line
 * summary of what was chosen (or of why nothing was).
 *
 * All tab/selection logic lives in ../questionState so it stays testable; this
 * component is the rendering plus the one network call.
 */
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
  const [expanded, setExpanded] = useState((isLast ?? false) || pending)
  const { animating, onTransitionEnd } = useCollapseTransition(expanded)

  // Auto-collapse once newer parts arrive — except while pending, where the
  // inputs must stay reachable.
  useEffect(() => {
    if (!isLast && !pending) setExpanded(false)
  }, [isLast, pending])

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

  const onSelect = (optionId: string) => {
    const stepped = select(qs, questions, optionId)
    setQs(stepped.state)
    if (stepped.submit) {
      void submit('answered', {
        session_id: sessionId,
        request_id: requestId,
        status: 'answered',
        answers: toAnswers(stepped.state, questions)
      })
    }
  }

  const onSaveCustom = () => {
    const stepped = saveCustom(qs, questions)
    setQs(stepped.state)
    if (stepped.submit) {
      void submit('answered', {
        session_id: sessionId,
        request_id: requestId,
        status: 'answered',
        answers: toAnswers(stepped.state, questions)
      })
    }
  }

  const current = questions[qs.tab]
  const ready = allAnswered(qs, questions)

  return (
    <div className="w-full overflow-hidden rounded-xl border border-msa-line-1 bg-msa-fill-1">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 border-none px-3 py-2 text-left transition-colors outline-none cursor-pointer bg-msa-fill-1"
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-msa-text-3">
          <AskIcon className="h-4 w-4" />
        </span>
        <Typography.Text className="!text-sm !text-msa-text-1 truncate">
          {t.chat.questionTitle}
        </Typography.Text>
        {!pending && (
          <span className="min-w-0 flex-1 truncate text-xs text-msa-text-3">
            {outcomeNote(t, state, step, questions)}
          </span>
        )}
        <ArrowDownIcon
          className={`h-3 w-3 shrink-0 text-msa-text-3 transition-transform duration-200 ${
            expanded ? 'rotate-180' : ''
          }`}
        />
      </button>

      <div
        className={`grid duration-200 ease-in-out ${
          animating ? 'transition-[grid-template-rows]' : ''
        }`}
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
        onTransitionEnd={onTransitionEnd}
      >
        <div className="overflow-hidden">
          <div className="border-t border-msa-line-1 px-3 py-2 space-y-2">
            {/* Tabs — only when there is more than one question. */}
            {questions.length > 1 && (
              <div className="flex flex-wrap gap-1" role="tablist">
                {questions.map((q, i) => (
                  <button
                    key={q.id}
                    type="button"
                    role="tab"
                    aria-selected={i === qs.tab}
                    disabled={qs.submitting}
                    onClick={() => setQs((prev) => setTab(prev, i))}
                    className={`flex items-center gap-1 rounded-lg border border-solid px-2 py-1 text-xs cursor-pointer ${
                      i === qs.tab
                        ? 'border-msa-line-1 bg-msa-fill-0 text-msa-text-1'
                        : 'border-transparent bg-transparent text-msa-text-3 hover:bg-msa-fill-2'
                    }`}
                  >
                    {isAnswered(qs, i) && (
                      <TaskDoneIcon className="h-3 w-3 text-msa-text-brand1" />
                    )}
                    {q.header || `${i + 1}`}
                  </button>
                ))}
              </div>
            )}

            {/* Live: the current question and its options. */}
            {live && current && (
              <>
                <div className="text-sm text-msa-text-1">
                  {current.question}
                </div>
                <div className="flex flex-col gap-1">
                  {current.options.map((option) => {
                    const picked = (qs.picked[qs.tab] ?? []).includes(option.id)
                    return (
                      <button
                        key={option.id}
                        type="button"
                        role={current.multi_select ? 'checkbox' : 'radio'}
                        aria-checked={picked}
                        disabled={qs.submitting}
                        onClick={() => onSelect(option.id)}
                        className={`rounded-lg border border-solid px-2 py-1.5 text-left text-sm cursor-pointer ${
                          picked
                            ? 'border-msa-text-brand1 bg-msa-fill-0 text-msa-text-1'
                            : 'border-msa-line-1 bg-msa-fill-0 text-msa-text-1 hover:bg-msa-fill-2'
                        }`}
                      >
                        <div>{option.label}</div>
                        {option.description && (
                          <div className="text-xs text-msa-text-3">
                            {option.description}
                          </div>
                        )}
                      </button>
                    )
                  })}

                  {/* Free text. Rendered by the CLIENT, never authored by the
                      model — see ui/interaction.py's CUSTOM_OPTION_ID. */}
                  {current.allow_custom !== false &&
                    (qs.editing ? (
                      <div className="space-y-1">
                        <MsaTextArea
                          autoFocus
                          maxLength={2000}
                          value={qs.draft}
                          placeholder={t.chat.questionCustomPlaceholder}
                          autoSize={{ minRows: 1, maxRows: 4 }}
                          onChange={(e) =>
                            setQs((prev) => editCustom(prev, e.target.value))
                          }
                          onPressEnter={(e) => {
                            if (e.shiftKey || e.nativeEvent.isComposing) return
                            e.preventDefault()
                            onSaveCustom()
                          }}
                        />
                        <div className="flex justify-end gap-2">
                          <MsaButton
                            variant="outlined"
                            onClick={() => setQs((prev) => cancelCustom(prev))}
                          >
                            {t.chat.questionCancelCustom}
                          </MsaButton>
                          <MsaButton variant="outlined" onClick={onSaveCustom}>
                            {t.chat.questionSaveCustom}
                          </MsaButton>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        disabled={qs.submitting}
                        onClick={() => onSelect(CUSTOM_OPTION_ID)}
                        className="rounded-lg border border-dashed border-msa-line-1 bg-msa-fill-0 px-2 py-1.5 text-left text-sm text-msa-text-2 hover:bg-msa-fill-2 cursor-pointer"
                      >
                        {qs.custom[qs.tab]
                          ? qs.custom[qs.tab]
                          : t.chat.questionCustomOption}
                      </button>
                    ))}
                </div>

                <div className="flex justify-end gap-2 pt-1">
                  <MsaButton
                    variant="outlined"
                    disabled={qs.submitting}
                    onClick={onSkip}
                  >
                    {t.chat.questionSkip}
                  </MsaButton>
                  {/* A single single-select question submits on selection, so
                      its Submit button would never be the thing that sends. */}
                  {(questions.length > 1 || current.multi_select) && (
                    <MsaButton
                      variant="primary"
                      disabled={qs.submitting || !ready}
                      onClick={onSubmit}
                    >
                      {t.chat.questionSubmit}
                    </MsaButton>
                  )}
                </div>
              </>
            )}

            {/* Terminal: what was asked and what came back. */}
            {!live && (
              <div className="space-y-1">
                {questions.map((q, i) => (
                  <div key={q.id} className="text-sm">
                    <span className="text-msa-text-3">
                      {q.header || q.question}
                    </span>{' '}
                    <span className="text-msa-text-1">
                      {state === 'answered'
                        ? resolvedLabels(step, qs, questions, i).join('、') || '—'
                        : '—'}
                    </span>
                  </div>
                ))}
                {questions.length === 0 && (
                  <div className="text-sm text-msa-text-3">
                    {outcomeNote(t, state, step, questions)}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
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
