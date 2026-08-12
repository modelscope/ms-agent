import type { AgentStep, AgentTask, StepKind } from '~/lib/agentProvider'

/**
 * Reference to an artifact/step the host can open in the workspace rail.
 * Kept here (was previously in ChatPanel) so message components and the
 * artifact panel share one import path.
 */
export interface ArtifactRef {
  name: string
  meta: Record<string, unknown>
}

/** Callback fired when a step card is clicked (opens the workspace rail). */
export type OnOpenStep = (step: AgentStep) => void

/** Callback fired when a user-attached file card is clicked: opens the
 * workspace rail and selects the given workspace-relative path. */
export type OnOpenFile = (path: string) => void

export type { AgentStep, AgentTask, StepKind }
