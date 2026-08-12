import type { AgentPart } from '~/lib/agentProvider'

export type TextPart = Extract<AgentPart, { kind: 'text' }>

export interface TurnSplit {
  /** The turn was stopped by the user (its parts carry the interrupt marker). */
  interrupted: boolean
  /** The tool-call loop closed (SDK `loop_end`) → the turn has a final summary
   * and its process history folds into a collapsible card. An interrupted turn
   * never reaches this state: it keeps the flat "processing" presentation. */
  loopDone: boolean
  /** Everything produced BEFORE the summary (thoughts, texts, tool rounds). */
  processParts: AgentPart[]
  /** The turn's final answer: its trailing text block, once the loop is done. */
  summary: TextPart | null
}

/**
 * Split one assistant turn into its process history and its final summary.
 *
 * The summary is the turn's TRAILING text block — the reply the tool-call loop
 * ended on (`loop_end` fires right after it). It is only split out once the
 * loop is done: while the turn streams, and forever for an interrupted turn,
 * every block stays "process" so nothing is hidden behind a header for work
 * that never concluded.
 */
export function splitTurn(parts: AgentPart[], streaming: boolean): TurnSplit {
  const interrupted = parts.some((p) => p.kind === 'interrupted')
  const loopDone = !streaming && !interrupted
  const last = parts[parts.length - 1]
  const hasSummary =
    loopDone && last != null && last.kind === 'text' && !!last.text
  return {
    interrupted,
    loopDone,
    processParts: hasSummary ? parts.slice(0, parts.length - 1) : parts,
    summary: hasSummary ? (last as TextPart) : null
  }
}
