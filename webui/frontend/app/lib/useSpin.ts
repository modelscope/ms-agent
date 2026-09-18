import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Spin state for a refresh button. `spin(run)` turns `spinning` on, runs `run`,
 * and keeps it on for at least `minMs`. The default matches one full turn of
 * Tailwind's `animate-spin` (1s), so an instant refresh still completes a whole
 * rotation and lands back at its starting angle instead of stopping mid-turn.
 * Calls made while already spinning are ignored.
 */
export function useSpin(
  minMs = 1000
): [boolean, (run: () => unknown) => void] {
  const [spinning, setSpinning] = useState(false)
  const busy = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    []
  )

  const spin = useCallback(
    (run: () => unknown) => {
      if (busy.current) return
      busy.current = true
      setSpinning(true)
      const started = Date.now()
      Promise.resolve()
        .then(run)
        .finally(() => {
          const rest = Math.max(0, minMs - (Date.now() - started))
          timer.current = setTimeout(() => {
            busy.current = false
            setSpinning(false)
          }, rest)
        })
    },
    [minMs]
  )

  return [spinning, spin]
}
