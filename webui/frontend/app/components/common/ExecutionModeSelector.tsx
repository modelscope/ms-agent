import { Button, Dropdown, Tooltip } from 'antd'
import { Link } from 'react-router'
import type { SessionModeSelection } from '~/lib/sessionMode'
import type { ExecutionMode } from '~/lib/types'
import { useT } from '~/lib/i18n'

export function ExecutionModeSelector({ selection, disabled }: { selection: SessionModeSelection; disabled: boolean }) {
  const { t } = useT()
  const labels = t.decisionMode
  const items = (['standard', 'decision'] as ExecutionMode[]).map(mode => ({
    key: mode,
    disabled: mode === 'decision' && !selection.available,
    label: <div className="max-w-[320px] py-1">
      <div className="font-medium">{labels[mode]}{selection.mode === mode ? ' ✓' : ''}</div>
      <div className="mt-1 whitespace-normal text-xs text-msa-text-3">{labels[`${mode}Description`]}</div>
    </div>
  }))
  return <div className="flex items-center gap-2">
    {!selection.available && !selection.locked && <Link className="text-xs text-msa-text-3" to="/settings/personalization">{labels.configure}</Link>}
    <Tooltip title={selection.locked ? labels.locked : labels.title}>
      <span><Dropdown trigger={['click']} disabled={disabled || selection.locked || selection.saving}
        menu={{ items, onClick: ({ key }) => { void selection.select(key as ExecutionMode).catch(() => {}) } }}>
        <Button size="small" type="text" loading={selection.saving} disabled={disabled}
          aria-label={labels.title} className="!text-xs !text-msa-text-2">
          {labels[selection.mode]} {selection.locked ? '·' : '⌄'}
        </Button>
      </Dropdown></span>
    </Tooltip>
  </div>
}
