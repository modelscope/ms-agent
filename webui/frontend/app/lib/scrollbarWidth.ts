import { useEffect } from 'react'

/* ==================================================================
 * Scrollbar width, measured once on the client into `--msa-scrollbar-w`.
 *
 * Why this exists: `scrollbar-gutter` only does something for *classic*
 * (space-taking) scrollbars. Under overlay scrollbars — macOS default, all
 * mobile — the bar floats over the content and the property is a no-op. So the
 * same CSS yields two different layouts, and a gutter-reserving box cannot be
 * balanced with a hardcoded number. There is no CSS query for this (the
 * `100vw - 100%` trick only sees the *page* scrollbar, which this app doesn't
 * have), so it has to be measured.
 * ================================================================== */

const VAR = '--msa-scrollbar-w'

/** Space a scrollbar takes from the content box. Returns 0 under overlay
 * scrollbars. Client only.
 *
 * `scrollbar-width` is set inline rather than inherited from app.css's `*` rule,
 * so the result does not depend on that sheet being parsed yet — in dev Vite
 * injects it from JS, well after the blocking script runs. Mirror app.css if it
 * ever changes. */
export function measureScrollbarWidth(): number {
  const probe = document.createElement('div')
  probe.style.cssText =
    'position:absolute;top:-9999px;left:-9999px;width:50px;height:50px;overflow:scroll;scrollbar-width:thin'
  document.body.appendChild(probe)
  const width = probe.offsetWidth - probe.clientWidth
  probe.remove()
  return width
}

/** Publishes the measured width on `<html>`. Call once at the app root.
 *
 * `SCROLLBAR_WIDTH_SCRIPT` has normally set it already; this re-runs the same
 * measurement as a fallback (if that script was blocked) and keeps it current
 * across resizes. Re-setting an unchanged value costs nothing. */
export function useScrollbarWidthVar(): void {
  useEffect(() => {
    let frame = 0
    const apply = () => {
      frame = 0
      document.documentElement.style.setProperty(
        VAR,
        `${measureScrollbarWidth()}px`
      )
    }
    apply()
    // Zoom keeps the bar's physical size, so its CSS-px width changes.
    const onResize = () => {
      frame ||= requestAnimationFrame(apply)
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [])
}

/** The same measurement as above, inlined to run *before* the app's markup is
 * laid out. An effect fires after the first paint, so the padding would be
 * computed against the `0px` default and then visibly jump once the real width
 * landed. Must stay in sync with `measureScrollbarWidth`.
 *
 * Goes at the top of `<body>` — the earliest point a probe can be appended.
 * Failing silently is fine, the `0px` default still stands. */
export const SCROLLBAR_WIDTH_SCRIPT = `(function(){try{var p=document.createElement('div');p.style.cssText='position:absolute;top:-9999px;left:-9999px;width:50px;height:50px;overflow:scroll;scrollbar-width:thin';document.body.appendChild(p);document.documentElement.style.setProperty('${VAR}',(p.offsetWidth-p.clientWidth)+'px');p.remove()}catch(e){}})()`
