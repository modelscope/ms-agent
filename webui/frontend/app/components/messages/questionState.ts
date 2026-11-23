/** 问答卡状态：逐题保留选择和自由输入，切题不提交也不丢弃内容。 */

/** Option id the backend reserves for a free-text answer (ui/interaction.py). */
export const CUSTOM_OPTION_ID = '__custom__'

export interface QuestionOptionView {
  id: string
  label: string
  description?: string
}

export interface QuestionView {
  id: string
  header: string
  question: string
  options: QuestionOptionView[]
  multi_select?: boolean
  allow_custom?: boolean
}

/** One question's answer, in the shape POST /api/chat/question accepts. */
export interface QuestionAnswerPayload {
  question_id: string
  option_ids: string[]
  custom_text: string
}

export interface QuestionState {
  /** Which question the card is showing. */
  tab: number
  /** Selected option ids per question index. */
  picked: string[][]
  /** Free text per question index (only meaningful with CUSTOM_OPTION_ID). */
  custom: string[]
  /** True from submit until the server's outcome frame lands. */
  submitting: boolean
}

export function createQuestionState(count: number): QuestionState {
  return {
    tab: 0,
    picked: Array.from({ length: count }, () => []),
    custom: Array.from({ length: count }, () => ''),
    submitting: false
  }
}

/** Grow/shrink the arrays if the card is re-rendered for a different ask. */
export function syncQuestionState(
  state: QuestionState,
  count: number
): QuestionState {
  if (state.picked.length === count) return state
  const next = createQuestionState(count)
  return {
    ...next,
    picked: Array.from({ length: count }, (_, i) => state.picked[i] ?? []),
    custom: Array.from({ length: count }, (_, i) => state.custom[i] ?? '')
  }
}

export function isAnswered(state: QuestionState, index: number): boolean {
  const ids = state.picked[index] ?? []
  return ids.length > 0 &&
    (!ids.includes(CUSTOM_OPTION_ID) || !!state.custom[index]?.trim())
}

export function allAnswered(
  state: QuestionState,
  questions: QuestionView[]
): boolean {
  return questions.length > 0 && questions.every((q, i) => {
    const ids = state.picked[i] ?? []
    return ids.length > 0 &&
      (q.multi_select || ids.length === 1) &&
      ids.every((id) => id === CUSTOM_OPTION_ID
        ? q.allow_custom !== false && !!state.custom[i]?.trim()
        : q.options.some((option) => option.id === id))
  })
}

export function setTab(state: QuestionState, tab: number): QuestionState {
  if (tab < 0 || tab >= state.picked.length || tab === state.tab) return state
  if (state.submitting) return state
  return { ...state, tab }
}

export interface QuestionStep {
  state: QuestionState
}

export function select(
  state: QuestionState,
  questions: QuestionView[],
  optionId: string
): QuestionStep {
  const question = questions[state.tab]
  if (!question || state.submitting) return { state }

  if (optionId === CUSTOM_OPTION_ID) {
    if (question.allow_custom === false) return { state }
  } else if (!question.options.some((option) => option.id === optionId)) {
    return { state }
  }
  const current = state.picked[state.tab] ?? []
  const next = question.multi_select
    ? current.includes(optionId)
      ? current.filter((id) => id !== optionId)
      : [...current, optionId]
    : [optionId]
  // 改选固定选项只改变选用状态，已输入的文字仍留在原题。
  return { state: store(state, state.tab, next) }
}

export function editCustom(
  state: QuestionState,
  value: string,
  questions: QuestionView[]
): QuestionState {
  const question = questions[state.tab]
  if (!question || question.allow_custom === false || state.submitting) return state
  const current = state.picked[state.tab] ?? []
  const picked = value.trim()
    ? question.multi_select
      ? [...current.filter((id) => id !== CUSTOM_OPTION_ID), CUSTOM_OPTION_ID]
      : [CUSTOM_OPTION_ID]
    : current.filter((id) => id !== CUSTOM_OPTION_ID)
  return { ...store(state, state.tab, picked),
    custom: replaceAt(state.custom, state.tab, value) }
}

/** The request body's `answers`, in question order. */
export function toAnswers(
  state: QuestionState,
  questions: QuestionView[]
): QuestionAnswerPayload[] {
  return questions.map((question, i) => ({
    question_id: question.id,
    option_ids: state.picked[i] ?? [],
    custom_text: (state.picked[i] ?? []).includes(CUSTOM_OPTION_ID)
      ? (state.custom[i] ?? '').trim() : ''
  }))
}

/** Labels for one question's answer, for the collapsed summary line. */
export function answerLabels(
  state: QuestionState,
  questions: QuestionView[],
  index: number
): string[] {
  const question = questions[index]
  if (!question) return []
  return (state.picked[index] ?? []).map((id) =>
    id === CUSTOM_OPTION_ID
      ? (state.custom[index] ?? '')
      : (question.options.find((o) => o.id === id)?.label ?? id)
  )
}

function store(
  state: QuestionState,
  index: number,
  picked: string[]
): QuestionState {
  return { ...state, picked: replaceAt(state.picked, index, picked) }
}

function replaceAt<T>(list: T[], index: number, value: T): T[] {
  const next = [...list]
  next[index] = value
  return next
}
