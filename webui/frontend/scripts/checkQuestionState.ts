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

// 选择和切题不隐式提交，单题也允许提交前回改。
{
  const questions = [q('q0', 'Format')]
  const step = select(start(questions), questions, 'q0_o0')
  check('单题选择保留在原题', step.state.tab === 0 && allAnswered(step.state, questions))
  check('点选不自动提交', !('submit' in step))
  const replaced = select(step.state, questions, 'q0_o1').state
  check('单选回改只选中最新选项', replaced.picked[0]?.join() === 'q0_o1')
}
{
  const questions = [q('q0', 'Features', true)]
  let s = select(start(questions), questions, 'q0_o0').state
  s = select(s, questions, 'q0_o1').state
  check('多选保留全部选项', s.picked[0]?.length === 2)
  s = select(s, questions, 'q0_o0').state
  check('再次点击取消选项', s.picked[0]?.join() === 'q0_o1')
}

// 自由输入即更新该题的本地答案，只有最终提交才发送至后台。
{
  const questions = [q('q0', 'Format')]
  let s = select(start(questions), questions, CUSTOM_OPTION_ID).state
  check('空自由输入不算已回答', !allAnswered(s, questions) && !isAnswered(s, 0))
  s = editCustom(s, '  Parquet  ', questions)
  check('输入原文留在状态中', s.custom[0] === '  Parquet  ')
  check('非空输入被选用', allAnswered(s, questions))
  check('提交时仅修剪首尾空白', toAnswers(s, questions)[0]?.custom_text === 'Parquet')
  check('显示标签采用真实输入', answerLabels(s, questions, 0)[0] === '  Parquet  ')
  s = editCustom(s, '   ', questions)
  check('清空输入取消自由答案', !isAnswered(s, 0) && !allAnswered(s, questions))
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
      check(`往返${round + 1}：第${i + 1}题输入未丢失`, s.custom[i] === `第${i + 1}题草稿\n第二行`)
      check(`往返${round + 1}：第${i + 1}题选中状态保留`, s.picked[i]?.includes(CUSTOM_OPTION_ID) === true)
    }
  }
  check('四题均有答案才允许提交', allAnswered(s, questions))
  const payload = toAnswers(s, questions)
  check('每题答案准确对应原题', payload.every((a, i) => a.question_id === questions[i]?.id && a.custom_text.startsWith(`第${i + 1}题`)))
  s = setTab(s, 1)
  s = select(s, questions, 'q1_o1').state
  check('选固定项不会删掉输入', s.custom[1] === '第2题草稿\n第二行')
  check('未选用的输入不提交', toAnswers(s, questions)[1]?.custom_text === '')
  s = setTab(setTab(s, 3), 1)
  check('切回仍可看到未选用输入', s.custom[1]?.startsWith('第2题') === true)
  s = select(s, questions, CUSTOM_OPTION_ID).state
  check('可重新选用保留的输入', toAnswers(s, questions)[1]?.custom_text.startsWith('第2题') === true)
  s = editCustom(s, '', questions)
  check('某题清空后禁止整组提交', !allAnswered(s, questions))
  check('不越过第一题', setTab(s, -1) === s)
  check('不越过最后一题', setTab(s, 4) === s)
  const busy = { ...s, submitting: true }
  check('提交期间不能切题', setTab(busy, 0) === busy)
  check('提交期间不能改输入', editCustom(busy, '新值', questions) === busy)
}
{
  const questions = [q('q0', 'Features', true)]
  let s = select(start(questions), questions, 'q0_o0').state
  s = select(s, questions, 'q0_o1').state
  s = editCustom(s, '额外要求', questions)
  check('多选可以同时包含自由输入', s.picked[0]?.length === 3)
  s = select(s, questions, CUSTOM_OPTION_ID).state
  check('取消自定义不丢弃文本', s.custom[0] === '额外要求' && toAnswers(s, questions)[0]?.custom_text === '')
  s = select(s, questions, CUSTOM_OPTION_ID).state
  check('重新选用不必再次输入', toAnswers(s, questions)[0]?.custom_text === '额外要求')
  s = editCustom(s, '', questions)
  check('清空只移除自定义答案', s.picked[0]?.length === 2 && allAnswered(s, questions))
}
{
  const questions = [q('q0', 'Format', false, false)]
  const s = start(questions)
  check('禁止自由输入时不修改状态', editCustom(s, 'text', questions) === s)
  check('禁止自由输入时不可选择自定义', select(s, questions, CUSTOM_OPTION_ID).state === s)
  check('未知选项不可选中', select(s, questions, 'unknown').state === s)
  check('无题目不可提交', !allAnswered(createQuestionState(0), []))
  const grown = syncQuestionState(s, 2)
  check('新增题目初始为空', grown.custom[1] === '' && grown.picked[1]?.length === 0)
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
