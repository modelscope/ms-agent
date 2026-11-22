import { useState } from 'react'
import { useSearchParams } from 'react-router'
import type { Scope } from '~/lib/types'
import { SkillCollection, type SkillImportSource } from './SkillCollection'

export function SkillsPanel({
  importing: controlled,
  onImportingChange
}: {
  importing?: SkillImportSource
  onImportingChange?: (value: SkillImportSource) => void
}) {
  const [searchParams] = useSearchParams()
  const [internal, setInternal] = useState<SkillImportSource>(null)
  const scope = (searchParams.get('scope') as Scope | null) ?? 'global'
  return (
    <SkillCollection
      key={scope}
      scope={scope}
      importing={controlled === undefined ? internal : controlled}
      onImportingChange={onImportingChange ?? setInternal}
    />
  )
}
