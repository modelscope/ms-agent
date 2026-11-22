/**
 * Pure state machine for the question card's tab flow.
 *
 * Kept free of React so it can be reasoned about (and tested) on its own: the
 * card is a rendering of this state, and every interaction is one transition
 * here. Modelled on opencode's question reducer for the same reason it exists
 * there — tabs, per-question selection and a free-text mode add up to more
 * combinations than component state should carry inline.
 *
 * Answering rules (fixed, so the card never has to decide):
 * - single question, single-select   -> picking submits immediately
 * - single question, multi-select    -> picking toggles; submit when ready
 * - several questions, single-select -> picking advances to the next
 *                                      unanswered tab; submit once all are done
 * - several questions, multi-select  -> picking toggles, no advance
 * - "type your own"                  -> enters editing mode; saving stores the
 *                                      text as that question's answer under the
 *                                      reserved CUSTOM_OPTION_ID
 * - skip                             -> the whole ask, never one question: a
 *                                      half-empty answer set has no meaning to
 *                                      the model
 */

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
  /** True while the free-text field is open for the current tab. */
  editing: boolean
  /** Draft of the free-text field (committed by saveCustom). */
  draft: string
  /** True from submit until the server's outcome frame lands. */
  submitting: boolean
}

export function createQuestionState(count: number): QuestionState {
  return {
    tab: 0,
    picked: Array.from({ length: count }, () => []),
    custom: Array.from({ length: count }, () => ''),
    editing: false,
    draft: '',
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
  return (state.picked[index] ?? []).length > 0
}

export function allAnswered(
  state: QuestionState,
  questions: QuestionView[]
): boolean {
  return questions.length > 0 && !state.editing && questions.every((q, i) => {
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
  // Leaving a tab abandons an uncommitted draft rather than carrying it to the
  // next question, where it would belong to a different answer.
  return { ...state, tab, editing: false, draft: '' }
}

/**
 * The outcome of a selection: the new state, plus whether the card should
 * submit now (the single-question single-select shortcut).
 */
export interface QuestionStep {
  state: QuestionState
  submit?: boolean
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
    // Never a one-click answer: it needs text, so it opens the field instead.
    return {
      state: { ...state, editing: true, draft: state.custom[state.tab] ?? '' }
    }
  }

  if (!question.options.some((option) => option.id === optionId)) return { state }
  if (question.multi_select) {
    const current = state.picked[state.tab] ?? []
    const next = current.includes(optionId)
      ? current.filter((id) => id !== optionId)
      : [...current, optionId]
    return { state: store(state, state.tab, next) }
  }

  // Single-select replaces, and drops any free text this question had: the
  // answer is now an option, and leaving the text behind would send both.
  let next = store(state, state.tab, [optionId])
  next = { ...next, custom: replaceAt(next.custom, state.tab, ''), editing: false, draft: '' }
  if (questions.length === 1) return { state: next, submit: true }
  const nextUnanswered = questions.findIndex(
    (_, i) => i !== state.tab && !isAnswered(next, i)
  )
  return {
    state: nextUnanswered === -1 ? next : { ...next, tab: nextUnanswered }
  }
}

export function editCustom(state: QuestionState, draft: string): QuestionState {
  return { ...state, draft }
}

export function cancelCustom(state: QuestionState): QuestionState {
  return { ...state, editing: false, draft: '' }
}

export function saveCustom(
  state: QuestionState,
  questions: QuestionView[]
): QuestionStep {
  const question = questions[state.tab]
  if (!question || question.allow_custom === false || state.submitting) return { state }
  const value = state.draft.trim()
  if (!value) {
    // An emptied field clears the answer it used to be, rather than leaving a
    // custom selection with nothing behind it.
    const cleared = store(
      state,
      state.tab,
      (state.picked[state.tab] ?? []).filter((id) => id !== CUSTOM_OPTION_ID)
    )
    return {
      state: {
        ...cleared,
        custom: replaceAt(cleared.custom, state.tab, ''),
        editing: false,
        draft: ''
      }
    }
  }

  const current = state.picked[state.tab] ?? []
  const picked = question.multi_select
    ? current.includes(CUSTOM_OPTION_ID)
      ? current
      : [...current, CUSTOM_OPTION_ID]
    : [CUSTOM_OPTION_ID]
  let next = store(state, state.tab, picked)
  next = {
    ...next,
    custom: replaceAt(next.custom, state.tab, value),
    editing: false,
    draft: ''
  }
  if (questions.length === 1 && !question.multi_select) {
    return { state: next, submit: true }
  }
  const nextUnanswered = questions.findIndex((_, i) => !isAnswered(next, i))
  return { state: !question.multi_select && nextUnanswered >= 0
    ? { ...next, tab: nextUnanswered } : next }
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
      ? state.custom[i] ?? '' : ''
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
