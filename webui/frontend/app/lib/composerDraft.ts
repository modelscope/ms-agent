import type { SlotConfigType } from '@ant-design/x/es/sender'
import type { AttachedFile } from '~/components/common/FileCard'

export interface ComposerDraft {
  text: string
  slots: SlotConfigType[]
  skills: { key: string; id: string; name: string }[]
  files: AttachedFile[]
}

// Tab-local drafts retain uploaded attachments and skill slots across navigation.
const drafts = new Map<string, ComposerDraft>()
const editors = new Map<string, () => boolean>()

export function readComposerDraft(id: string): ComposerDraft | undefined {
  return drafts.get(id)
}

export function saveComposerDraft(id: string, draft: ComposerDraft) {
  if (!draft.text && !draft.skills.length && !draft.files.length) drafts.delete(id)
  else {
    drafts.delete(id)
    drafts.set(id, draft)
    if (drafts.size > 50) drafts.delete(drafts.keys().next().value!)
  }
}

export function registerComposer(id: string, save: () => boolean) {
  editors.set(id, save)
  return () => { if (editors.get(id) === save) editors.delete(id) }
}

export function preserveComposerDraft(id: string): boolean {
  return editors.get(id)?.() ?? true
}
