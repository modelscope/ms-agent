interface MsaSwitchProps {
  checked?: boolean
  onChange?: (checked: boolean) => void
  disabled?: boolean
  className?: string
}

export function MsaSwitch({
  checked = false,
  onChange,
  disabled = false,
  className = ''
}: MsaSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={`
        relative inline-flex h-[18px] w-[32px] shrink-0 cursor-pointer items-center
        rounded-sm border-none p-[3px] transition-colors duration-200
        ${checked ? 'bg-msa-deco-green' : 'bg-msa-fill-5'}
        ${disabled ? 'cursor-not-allowed opacity-50' : ''}
        ${className}
      `}
    >
      <span
        className={`
          inline-block h-[12px] w-[12px] rounded-[4px] shadow-sm transition-transform duration-200
          ${checked ? 'translate-x-[12px] bg-white' : 'translate-x-0 bg-white'}
        `}
      />
    </button>
  )
}
