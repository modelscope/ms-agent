/**
 * Drives the REAL question reducer through the interactions the card exposes,
 * plus the frame sequences the streaming layer feeds it. Run with
 * `pnpm check:questions`.
 *
 * Two things are checked together on purpose, because between them they are the
 * whole contract of an answerable card:
 *   1. the tab/selection state machine (questionState.ts) — what "answered"
 *      means, when the card may submit, and what a free-text answer becomes;
 *   2. the streaming merge (agentProvider.ts) — an outcome frame must close the
 *      card it belongs to WITHOUT losing the questions, which only the ask
 *      frame ever carried.
 */
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
  toAnswers,
  type QuestionState,
  type QuestionView
} from '~/components/messages/questionState'
import {
  applyChunk,
  type AgentChunk,
  type AgentMessage
} from '~/lib/agentProvider'

let failed = 0
function check(name: string, ok: boolean, why = '') {
  if (ok) {
    console.log(`  ✓ ${name}`)
    return
  }
  failed += 1
  console.error(`  ✗ ${name}${why ? `: ${why}` : ''}`)
}

const q = (
  id: string,
  header: string,
  multi = false,
  allowCustom = true
): QuestionView => ({
  id,
  header,
  question: `${header}?`,
  options: [
    { id: `${id}_o0`, label: `${header} A` },
    { id: `${id}_o1`, label: `${header} B` }
  ],
  multi_select: multi,
  allow_custom: allowCustom
})

const start = (questions: QuestionView[]): QuestionState =>
  createQuestionState(questions.length)

// ── one question ───────────────────────────────────────────────────────────

{
  const questions = [q('q0', 'Format')]
  const step = select(start(questions), questions, 'q0_o0')
  check(
    'a single single-select question submits on selection',
    step.submit === true && step.state.picked[0]?.[0] === 'q0_o0',
    'picking is the whole interaction; a Submit button would never be pressed'
  )
}

{
  const questions = [q('q0', 'Features', true)]
  const first = select(start(questions), questions, 'q0_o0')
  let s = first.state
  const stillOpen = first.submit !== true && allAnswered(s, questions)
  s = select(s, questions, 'q0_o1').state
  check(
    'multi-select accumulates and never auto-submits',
    stillOpen && s.picked[0]?.length === 2,
    JSON.stringify(s.picked)
  )
  s = select(s, questions, 'q0_o0').state
  check('picking a chosen option again removes it', s.picked[0]?.length === 1)
}

// ── several questions ──────────────────────────────────────────────────────

{
  const questions = [q('q0', 'Format'), q('q1', 'Chart'), q('q2', 'Name')]
  let s = start(questions)
  s = select(s, questions, 'q0_o0').state
  check('answering advances to the next unanswered tab', s.tab === 1)
  s = select(s, questions, 'q1_o1').state
  check('and keeps advancing', s.tab === 2)
  check(
    'submit stays unavailable while a question is unanswered',
    !allAnswered(s, questions)
  )
  s = select(s, questions, 'q2_o0').state
  check('submit unlocks once every question is answered', allAnswered(s, questions))
  check(
    'the last answer does not auto-submit a multi-question ask',
    select(start(questions), questions, 'q0_o0').submit !== true
  )
}

{
  const questions = [q('q0', 'Format'), q('q1', 'Chart')]
  let s = start(questions)
  s = select(s, questions, 'q0_o0').state // now on tab 1
  s = setTab(s, 0)
  s = select(s, questions, 'q0_o1').state
  check(
    'going back replaces that answer rather than adding one',
    s.picked[0]?.length === 1 && s.picked[0]?.[0] === 'q0_o1'
  )
  check(
    'and it does not advance past a tab that is already answered',
    s.tab === 1,
    `tab=${s.tab}`
  )
}

// ── free text ──────────────────────────────────────────────────────────────

{
  const questions = [q('q0', 'Format')]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  check(
    'choosing "type your own" opens the field instead of answering',
    s.editing === true && !isAnswered(s, 0)
  )
  s = editCustom(s, '  Parquet  ')
  const saved = saveCustom(s, questions)
  s = saved.state
  check(
    'saving stores the text under the reserved custom id',
    s.picked[0]?.[0] === CUSTOM_OPTION_ID && s.custom[0] === 'Parquet',
    JSON.stringify([s.picked[0], s.custom[0]])
  )
  check('and submits, being the only question', saved.submit === true)
  check('the label shown is the text itself', answerLabels(s, questions, 0)[0] === 'Parquet')
}

{
  const questions = [q('q0', 'Format')]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  s = editCustom(s, 'Parquet')
  s = saveCustom(s, questions).state
  s = select(s, questions, CUSTOM_OPTION_ID).state
  s = editCustom(s, '   ')
  s = saveCustom(s, questions).state
  check(
    'emptying the field clears the answer it used to be',
    !isAnswered(s, 0) && s.custom[0] === '',
    'otherwise a custom selection is submitted with nothing behind it'
  )
}

{
  const questions = [q('q0', 'Format')]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  s = editCustom(s, 'Parquet')
  s = saveCustom(s, questions).state
  s = select(s, questions, 'q0_o0').state
  check(
    'picking an option drops the free text it replaces',
    s.picked[0]?.[0] === 'q0_o0' && s.custom[0] === '',
    'sending both would leave the backend to guess which the user meant'
  )
}

{
  const questions = [q('q0', 'Format'), q('q1', 'Chart')]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  s = editCustom(s, 'draft for q0')
  s = setTab(s, 1)
  check(
    'leaving a tab abandons its uncommitted draft',
    s.editing === false && s.draft === '',
    'carrying it over would attach it to a different question'
  )
  s = cancelCustom(editCustom(s, 'x'))
  check('cancelling clears the draft too', s.draft === '')
}

// ── the request body ───────────────────────────────────────────────────────

{
  const questions = [q('q0', 'Format'), q('q1', 'Features', true)]
  let s = start(questions)
  s = select(s, questions, 'q0_o0').state
  s = select(s, questions, 'q1_o0').state
  s = select(s, questions, 'q1_o1').state
  const answers = toAnswers(s, questions)
  check(
    'answers are emitted in question order, ids only',
    answers.length === 2 &&
      answers[0]!.question_id === 'q0' &&
      answers[1]!.option_ids.length === 2 &&
      !('labels' in answers[0]!),
    JSON.stringify(answers)
  )
}

{
  const questions = [q('q0', 'Format'), q('q1', 'Chart')]
  const grown = syncQuestionState(start([q('q0', 'Format')]), questions.length)
  check(
    'state resized for a different ask keeps no stale slots',
    grown.picked.length === 2 && grown.picked[1]?.length === 0
  )
}

// ── the streaming merge ────────────────────────────────────────────────────

const ask = (callId: string, requestId: string): AgentChunk => ({
  type: 'step',
  content: '',
  meta: {
    kind: 'question',
    state: 'pending',
    call_id: callId,
    request_id: requestId,
    session_id: 'sess-1',
    questions: [q('q0', 'Format')]
  }
})
const outcome = (callId: string, state: string): AgentChunk => ({
  type: 'step',
  content: '',
  meta: {
    kind: 'question',
    state,
    call_id: callId,
    answers: [{ question_id: 'q0', labels: ['Format B'] }]
  }
})

function reduce(frames: AgentChunk[]): AgentMessage {
  let msg: AgentMessage = { role: 'assistant', content: '' }
  for (const f of frames) msg = applyChunk(msg, f)
  return msg
}

{
  const parts = reduce([ask('call-1', 'req-1'), outcome('call-1', 'answered')])
    .parts!
  const steps = parts.filter((p) => p.kind === 'step')
  check(
    'an outcome frame closes the ask in place instead of appending a card',
    steps.length === 1,
    `${steps.length} step parts`
  )
  const meta = steps[0]!.kind === 'step' ? steps[0]!.step.meta : {}
  check('the card now reads as answered', meta.state === 'answered')
  check(
    'and it still knows what was asked',
    Array.isArray(meta.questions) && meta.questions.length === 1,
    'the outcome frame carries no questions; losing them empties the summary'
  )
  check(
    'the answers arrive with it',
    JSON.stringify(meta.answers) ===
      JSON.stringify([{ question_id: 'q0', labels: ['Format B'] }])
  )
}

{
  const parts = reduce([
    ask('call-1', 'req-1'),
    ask('call-2', 'req-2'),
    outcome('call-2', 'skipped')
  ]).parts!
  const steps = parts.filter((p) => p.kind === 'step')
  check(
    'an outcome only closes its own ask',
    steps.length === 2 &&
      (steps[0]!.kind === 'step' ? steps[0]!.step.meta.state : '') ===
        'pending' &&
      (steps[1]!.kind === 'step' ? steps[1]!.step.meta.state : '') === 'skipped'
  )
}

{
  const parts = reduce([outcome('call-9', 'cancelled')]).parts!
  check(
    'an orphan outcome still renders (a replay may start mid-ask)',
    parts.filter((p) => p.kind === 'step').length === 1
  )
}

{
  const questions = [q('q0', 'Features', true)]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  s = saveCustom(editCustom(s, '额外要求'), questions).state
  s = select(s, questions, 'q0_o0').state
  check('多选包含自由文本', toAnswers(s, questions)[0]?.custom_text === '额外要求')
  s = saveCustom(editCustom(select(s, questions, CUSTOM_OPTION_ID).state, ''), questions).state
  check('清空自由文本不会丢失其余选项', toAnswers(s, questions)[0]?.option_ids[0] === 'q0_o0')
  check('无题目不可提交', !allAnswered(createQuestionState(0), []))
  check('未知选项不可选中', select(start(questions), questions, 'unknown').state.picked[0]?.length === 0)
}

if (failed) {
  console.error(`\n${failed} check(s) failed`)
  process.exit(1)
}
console.log('\nall question checks ok')
