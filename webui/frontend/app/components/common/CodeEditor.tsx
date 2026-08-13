import { lazy, Suspense, useEffect, useState } from 'react'
import { DeferredSkeleton } from '~/components/common/DeferredSkeleton'
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
  /**
   * Hint shown while the editor is empty. Rendered as a scoped overlay that
   * copies monaco's own font metrics and content offsets at mount, so it lands
   * on the caret's baseline and indent.
   *
   * monaco's built-in `placeholder` option is deliberately NOT used: it is
   * single-line (`text-wrap: nowrap` + `overflow: hidden`), so a multi-line
   * template like the MCP JSON sample would show only its first `{`.
   */
  placeholder?: string
}

interface InternalProps extends Props {
  dark?: boolean
}

/** Placeholder shown for every stage of getting the editor on screen: the SSR /
 * pre-mount pass, the lazy chunk download, and monaco's own init (whose default
 * is the literal text "Loading..."). One shape for all three, wrapped in the
 * project's anti-flicker gate, so a fast load shows nothing at all instead of a
 * skeleton (or a word) blinking in and out.
 *
 * The OUTER div owns the height: callers pass `height="100%"` (workspace
 * editor), and a percentage on `Skeleton.Input` is dead — antd forwards `style`
 * to an inner element whose wrapper div is auto-height, so `100%` resolves
 * against nothing and the placeholder collapses to 0 (invisible). Line rows
 * carry their own intrinsic height instead, and they read like code lines. */
function EditorSkeleton({ height }: { height: number | string }) {
  return (
    <div style={{ height }} className="w-full overflow-hidden">
      <DeferredSkeleton rows={10} className="p-4" />
    </div>
  )
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
  fullFeatures,
  placeholder
}: Props) {
  const [mounted, setMounted] = useState(false)
  const { theme } = useTheme()
  const dark = theme === 'dark'

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) {
    return <EditorSkeleton height={height} />
  }

  return (
    <Suspense fallback={<EditorSkeleton height={height} />}>
      <LazyEditor
        value={value}
        onChange={onChange}
        language={language}
        height={height}
        readOnly={readOnly}
        lineNumbers={lineNumbers}
        fullFeatures={fullFeatures}
        placeholder={placeholder}
        dark={dark}
      />
    </Suspense>
  )
}

const LazyEditor = lazy(async () => {
  const [
    monaco,
    mod,
    EditorWorker,
    JsonWorker,
    CssWorker,
    HtmlWorker,
    TsWorker
  ] = await Promise.all([
    import('monaco-editor'),
    import('@monaco-editor/react'),
    import('monaco-editor/esm/vs/editor/editor.worker?worker'),
    import('monaco-editor/esm/vs/language/json/json.worker?worker'),
    import('monaco-editor/esm/vs/language/css/css.worker?worker'),
    import('monaco-editor/esm/vs/language/html/html.worker?worker'),
    import('monaco-editor/esm/vs/language/typescript/ts.worker?worker')
  ])

  // Every language service monaco ships with. The label monaco passes here is
  // the language id, and one worker backs a family of ids (a css worker serves
  // scss/less, the html worker serves handlebars/razor, the ts worker serves
  // javascript). Anything else — python, go, rust, yaml, sql, shell… — has no
  // upstream worker at all: those get Monarch syntax highlighting plus the
  // generic editor worker (find/replace, folding, diffing), which is the most
  // monaco offers for them.
  ;(globalThis as { MonacoEnvironment?: unknown }).MonacoEnvironment = {
    getWorker(_workerId: string, label: string) {
      switch (label) {
        case 'json':
          return new JsonWorker.default()
        case 'css':
        case 'scss':
        case 'less':
          return new CssWorker.default()
        case 'html':
        case 'handlebars':
        case 'razor':
          return new HtmlWorker.default()
        case 'typescript':
        case 'javascript':
          return new TsWorker.default()
        default:
          return new EditorWorker.default()
      }
    }
  }

  // Single-file editing context: the workspace opens files standalone, with no
  // tsconfig and no sibling modules resolvable. Left at its defaults the TS
  // service floods the gutter with "cannot find module" / "cannot redeclare"
  // errors that say nothing about the file itself, so semantic validation is
  // off while syntax validation (real typos) stays on. JSX is enabled so
  // .tsx/.jsx files tokenize and complete correctly.
  //
  // These live on monaco's TOP-LEVEL language namespaces as of 0.55
  // (`monaco.typescript`, `monaco.json`, …); the old `monaco.languages.*`
  // aliases are deprecated stubs typed `{ deprecated: true }`.
  for (const d of [
    monaco.typescript.typescriptDefaults,
    monaco.typescript.javascriptDefaults
  ]) {
    d.setDiagnosticsOptions({
      noSemanticValidation: true,
      noSyntaxValidation: false
    })
    d.setCompilerOptions({
      target: monaco.typescript.ScriptTarget.ESNext,
      module: monaco.typescript.ModuleKind.ESNext,
      moduleResolution: monaco.typescript.ModuleResolutionKind.NodeJs,
      jsx: monaco.typescript.JsxEmit.ReactJSX,
      allowJs: true,
      allowNonTsExtensions: true,
      esModuleInterop: true,
      noEmit: true
    })
  }

  // JSON: schema-less files still get structural validation + formatting,
  // comments tolerated (many config files in the wild are JSONC).
  monaco.json.jsonDefaults.setDiagnosticsOptions({
    validate: true,
    allowComments: true,
    schemaValidation: 'warning',
    trailingCommas: 'warning'
  })

  mod.loader.config({ monaco })

  return {
    default: (p: InternalProps) => {
      const full = p.fullFeatures ?? false
      // Geometry copied from the live editor so the placeholder overlay sits
      // exactly where typed text would: monaco's own font metrics (size, family,
      // line height) plus the horizontal offset of the content area (gutter +
      // decorations) and the configured top padding.
      const [metrics, setMetrics] = useState<{
        fontFamily: string
        fontSize: number
        lineHeight: number
        left: number
        top: number
      } | null>(null)
      const showPlaceholder = !!p.placeholder && !p.value
      const [editor, setEditor] = useState<
        import('monaco-editor').editor.IStandaloneCodeEditor | null
      >(null)

      // Measure once mounted, then follow layout/option changes. Kept in an
      // effect (not in `onMount`) because @monaco-editor/react calls onMount as
      // `onMount.current(editor, monaco)` and DISCARDS its return value — a
      // cleanup returned from there would never run and the listeners would leak.
      useEffect(() => {
        if (!editor || !p.placeholder) return
        const read = () => {
          const info = editor.getOption(monaco.editor.EditorOption.fontInfo)
          const pad = editor.getOption(monaco.editor.EditorOption.padding)
          setMetrics({
            fontFamily: info.fontFamily,
            fontSize: info.fontSize,
            lineHeight: info.lineHeight,
            // Where column 1 actually starts (gutter + decorations).
            left: editor.getLayoutInfo().contentLeft,
            top: pad?.top ?? 0
          })
        }
        read()
        const subs = [
          editor.onDidLayoutChange(read),
          editor.onDidChangeConfiguration(read)
        ]
        return () => subs.forEach((s) => s.dispose())
      }, [editor, p.placeholder])

      return (
        <div className="relative h-full">
          {showPlaceholder && metrics && (
            <pre
              aria-hidden
              className="pointer-events-none absolute inset-0 z-10 m-0 overflow-hidden whitespace-pre text-msa-text-3 opacity-60"
              style={{
                fontFamily: metrics.fontFamily,
                fontSize: metrics.fontSize,
                lineHeight: `${metrics.lineHeight}px`,
                paddingLeft: metrics.left,
                paddingTop: metrics.top
              }}
            >
              {p.placeholder}
            </pre>
          )}
          <mod.default
            value={p.value}
            onChange={(v) => p.onChange?.(v ?? '')}
            height={p.height}
            language={p.language}
            theme={p.dark ? 'vs-dark' : 'vs'}
            // Replaces @monaco-editor/react's default "Loading..." text, shown
            // while it boots monaco after the chunk has arrived.
            loading={<EditorSkeleton height={p.height ?? 320} />}
            onMount={setEditor}
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
        </div>
      )
    }
  }
})
