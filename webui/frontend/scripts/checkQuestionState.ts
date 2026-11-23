/**
 * Question state and streaming-merge regressions. Run `pnpm check:questions`.
 */
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

// Selection and navigation never submit implicitly.
{
  const questions = [q('q0', 'Format')]
  const step = select(start(questions), questions, 'q0_o0')
  check('selection stays on the current question', step.state.tab === 0 && allAnswered(step.state, questions))
  check('selection does not submit', !('submit' in step))
  const replaced = select(step.state, questions, 'q0_o1').state
  check('single-select replaces the previous choice', replaced.picked[0]?.join() === 'q0_o1')
}
{
  const questions = [q('q0', 'Features', true)]
  let s = select(start(questions), questions, 'q0_o0').state
  s = select(s, questions, 'q0_o1').state
  check('multi-select retains all choices', s.picked[0]?.length === 2)
  s = select(s, questions, 'q0_o0').state
  check('clicking again deselects an option', s.picked[0]?.join() === 'q0_o1')
}

// Custom input stays local until the final submission.
{
  const questions = [q('q0', 'Format')]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  check('empty custom input is unanswered', !allAnswered(s, questions) && !isAnswered(s, 0))
  s = editCustom(s, '  Parquet  ', questions)
  check('state retains the raw draft', s.custom[0] === '  Parquet  ')
  check('nonempty custom input is selected', allAnswered(s, questions))
  check('submission trims surrounding whitespace', toAnswers(s, questions)[0]?.custom_text === 'Parquet')
  check('display labels retain the raw draft', answerLabels(s, questions, 0)[0] === '  Parquet  ')
  s = editCustom(s, '   ', questions)
  check('clearing input deselects the custom answer', !isAnswered(s, 0) && !allAnswered(s, questions))
}
{
  const questions = [q('q0', 'Format'), q('q1', 'Language'), q('q2', 'Charts', true), q('q3', 'Name')]
  let s = start(questions)
  for (let i = 0; i < questions.length; i++) {
    s = setTab(s, i)
    s = editCustom(s, `第${i + 1}题草稿\n第二行`, questions)
  }
  for (let round = 0; round < 5; round++) {
    for (let i = questions.length - 1; i >= 0; i--) {
      s = setTab(s, i)
      check(`round ${round + 1}: question ${i + 1} draft survives`, s.custom[i] === `第${i + 1}题草稿\n第二行`)
      check(`round ${round + 1}: question ${i + 1} selection survives`, s.picked[i]?.includes(CUSTOM_OPTION_ID) === true)
    }
  }
  check('all four questions must be answered', allAnswered(s, questions))
  const payload = toAnswers(s, questions)
  check('answers match their question IDs', payload.every((a, i) => a.question_id === questions[i]?.id && a.custom_text.startsWith(`第${i + 1}题`)))
  s = setTab(s, 1)
  s = select(s, questions, 'q1_o1').state
  check('fixed choices preserve custom drafts', s.custom[1] === '第2题草稿\n第二行')
  check('unselected drafts are not submitted', toAnswers(s, questions)[1]?.custom_text === '')
  s = setTab(setTab(s, 3), 1)
  check('navigation preserves unselected drafts', s.custom[1]?.startsWith('第2题') === true)
  s = select(s, questions, CUSTOM_OPTION_ID).state
  check('retained drafts can be reselected', toAnswers(s, questions)[1]?.custom_text.startsWith('第2题') === true)
  s = editCustom(s, '', questions)
  check('an unanswered question blocks submission', !allAnswered(s, questions))
  check('navigation respects the lower bound', setTab(s, -1) === s)
  check('navigation respects the upper bound', setTab(s, 4) === s)
  const busy = { ...s, submitting: true }
  check('submission blocks navigation', setTab(busy, 0) === busy)
  check('submission blocks editing', editCustom(busy, '新值', questions) === busy)
}
{
  const questions = [q('q0', 'Features', true)]
  let s = select(start(questions), questions, 'q0_o0').state
  s = select(s, questions, 'q0_o1').state
  s = editCustom(s, '额外要求', questions)
  check('multi-select accepts custom input alongside options', s.picked[0]?.length === 3)
  s = select(s, questions, CUSTOM_OPTION_ID).state
  check('deselecting custom input preserves its draft', s.custom[0] === '额外要求' && toAnswers(s, questions)[0]?.custom_text === '')
  s = select(s, questions, CUSTOM_OPTION_ID).state
  check('reselecting custom input restores its draft', toAnswers(s, questions)[0]?.custom_text === '额外要求')
  s = editCustom(s, '', questions)
  check('clearing custom input preserves fixed choices', s.picked[0]?.length === 2 && allAnswered(s, questions))
}
{
  const questions = [q('q0', 'Format', false, false)]
  const s = start(questions)
  check('disabled custom input cannot change state', editCustom(s, 'text', questions) === s)
  check('disabled custom options cannot be selected', select(s, questions, CUSTOM_OPTION_ID).state === s)
  check('unknown options cannot be selected', select(s, questions, 'unknown').state === s)
  check('empty question sets cannot be submitted', !allAnswered(createQuestionState(0), []))
  const grown = syncQuestionState(s, 2)
  check('new questions start unanswered', grown.custom[1] === '' && grown.picked[1]?.length === 0)
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

if (failed) {
  console.error(`\n${failed} check(s) failed`)
  process.exit(1)
}
console.log('\nall question checks ok')
