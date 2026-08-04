import { Skeleton } from 'antd'
import { lazy, Suspense, useEffect, useState } from 'react'
import { useTheme } from '~/lib/theme'

interface Props {
  value: string
  onChange?: (next: string) => void
  /** Monaco language id — e.g. 'json', 'markdown', 'python'. Default 'plaintext'. */
  language?: string
  height?: number | string
  readOnly?: boolean
  /** Toggle line numbers. Off by default to match the right-rail compact look. */
  lineNumbers?: boolean
  /**
   * Enable the complete file-editing chrome — line numbers, folding controls,
   * minimap, sticky scroll, current-line highlight and glyph margin — for real
   * file editing/viewing (e.g. the workspace editor) rather than the compact
   * JSON config boxes. Implies line numbers on.
   */
  fullFeatures?: boolean
}

interface InternalProps extends Props {
  dark?: boolean
}

/**
 * Monaco-based code editor.
 *
 * - Client-only: monaco-editor pulls `window` globals at import time and
 *   doesn't survive SSR. We render a Skeleton on the server pass and lazy
 *   import the editor after mount.
 * - Local loader: `@monaco-editor/react` defaults to fetching monaco from
 *   jsDelivr; we point it at the bundled `monaco-editor` so the app works
 *   offline / inside corporate networks.
 * - Vite-friendly workers: monaco needs web workers for language services.
 *   We register the editor + JSON workers via `?worker` imports so Vite
 *   emits proper bundles instead of trying to fetch them at runtime. Other
 *   languages use the generic editor worker (no IntelliSense but full
 *   syntax highlighting and editing).
 */
export function CodeEditor({
  value,
  onChange,
  language = 'plaintext',
  height = 320,
  readOnly,
  lineNumbers,
  fullFeatures
}: Props) {
  const [mounted, setMounted] = useState(false)
  const { theme } = useTheme()
  const dark = theme === 'dark'

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) {
    return <Skeleton.Input active block style={{ height }} />
  }

  return (
    <Suspense fallback={<Skeleton.Input active block style={{ height }} />}>
      <LazyEditor
        value={value}
        onChange={onChange}
        language={language}
        height={height}
        readOnly={readOnly}
        lineNumbers={lineNumbers}
        fullFeatures={fullFeatures}
        dark={dark}
      />
    </Suspense>
  )
}

const LazyEditor = lazy(async () => {
  const [monaco, mod, EditorWorker, JsonWorker] = await Promise.all([
    import('monaco-editor'),
    import('@monaco-editor/react'),
    import('monaco-editor/esm/vs/editor/editor.worker?worker'),
    import('monaco-editor/esm/vs/language/json/json.worker?worker')
  ])

  ;(globalThis as { MonacoEnvironment?: unknown }).MonacoEnvironment = {
    getWorker(_workerId: string, label: string) {
      if (label === 'json') return new JsonWorker.default()
      return new EditorWorker.default()
    }
  }

  mod.loader.config({ monaco })

  return {
    default: (p: InternalProps) => {
      const full = p.fullFeatures ?? false
      return (
        <mod.default
          value={p.value}
          onChange={(v) => p.onChange?.(v ?? '')}
          height={p.height}
          language={p.language}
          theme={p.dark ? 'vs-dark' : 'vs'}
          options={{
            readOnly: p.readOnly,
            // Reflow when the container resizes (e.g. dragging the workspace
            // splitter or resizing the window).
            automaticLayout: true,
            scrollBeyondLastLine: false,
            fontSize: full ? 13 : 12,
            fontLigatures: true,
            tabSize: 2,
            wordWrap: 'on',
            padding: { top: 8, bottom: 8 },
            // Editing quality-of-life — useful in every scenario.
            bracketPairColorization: { enabled: true },
            matchBrackets: 'always',
            autoClosingBrackets: 'languageDefined',
            autoClosingQuotes: 'languageDefined',
            autoSurround: 'languageDefined',
            autoIndent: 'full',
            formatOnPaste: true,
            guides: { indentation: true, bracketPairs: true },
            cursorBlinking: 'smooth',
            cursorSmoothCaretAnimation: 'on',
            smoothScrolling: true,
            mouseWheelZoom: true,
            multiCursorModifier: 'ctrlCmd',
            find: { seedSearchStringFromSelection: 'selection' },
            scrollbar: {
              useShadows: false,
              verticalScrollbarSize: 10,
              horizontalScrollbarSize: 10
            },
            // Full file-editing chrome vs. compact config box.
            lineNumbers: full || p.lineNumbers ? 'on' : 'off',
            folding: true,
            foldingHighlight: true,
            showFoldingControls: full ? 'always' : 'mouseover',
            glyphMargin: full,
            lineDecorationsWidth: full ? 10 : 0,
            stickyScroll: { enabled: full },
            renderLineHighlight: full ? 'all' : 'line',
            occurrencesHighlight: full ? 'singleFile' : 'off',
            minimap: {
              enabled: full,
              autohide: 'mouseover',
              renderCharacters: false,
              maxColumn: 80
            }
          }}
        />
      )
    }
  }
})
