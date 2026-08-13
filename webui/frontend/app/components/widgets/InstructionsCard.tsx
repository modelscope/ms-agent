import { useEffect, useState } from 'react'
import { api } from '~/lib/api'
import { useT } from '~/lib/i18n'
import type { Scope } from '~/lib/types'
import { MsaTextArea } from '~/components/common/MsaTextArea'
import { WidgetCard } from './WidgetCard'
import InstructionIcon from '~/assets/icons/custom-instruction.svg?react'

export function InstructionsCard({ scope }: { scope: Scope }) {
  const { t } = useT()
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    setLoaded(false)
    api.getInstruction(scope).then((r) => {
      setContent(r.content)
      setLoaded(true)
    })
  }, [scope])

  const onBlur = async () => {
    if (!loaded) return
    await api.putInstruction(scope, content)
  }

  return (
    <WidgetCard
      title={t.widgets.instructionsTitle}
      icon={<InstructionIcon className="h-5 w-5" />}
    >
      <MsaTextArea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onBlur={onBlur}
        autoSize={{ minRows: 10, maxRows: 10 }}
        placeholder={t.widgets.instructionsPlaceholder}
      />
    </WidgetCard>
  )
}
