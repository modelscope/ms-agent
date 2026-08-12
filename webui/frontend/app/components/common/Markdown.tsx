import { Actions, CodeHighlighter, Mermaid } from '@ant-design/x'
import { ConfigProvider } from 'antd'
import { useContext } from 'react'
import { XMarkdown } from '@ant-design/x-markdown'
import type { ComponentProps } from '@ant-design/x-markdown'
import Latex from '@ant-design/x-markdown/plugins/Latex'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useTheme } from '~/lib/theme'
import CopyIcon from '~/assets/icons/copy.svg?react'
import './Markdown.css'
// Typography themes (x-markdown-light / x-markdown-dark) are @imported in
// app.css — importing the package css here would crash Node SSR (deep css
// imports of an externalized package bypass Vite's pipeline).

interface Props {
  content: string
  /** Pass true while the content is still being streamed in. */
  streaming?: boolean
  /** Handle a leading YAML frontmatter block (```---…---```). CommonMark has
   * no frontmatter concept (and x-markdown ships no extension for it), so the
   * raw block would render as a broken heading/paragraph mix. When enabled,
   * the block is re-emitted as a fenced ```yaml code block instead. */
  frontmatter?: boolean
}

const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/

function withFrontmatterAsYaml(src: string): string {
  const m = FRONTMATTER_RE.exec(src)
  if (!m) return src
  return '```yaml\n' + m[1] + '\n```\n\n' + src.slice(m[0].length)
}

/** Flatten the ReactNode children of a mapped tag into plain text (fenced
 * code bodies arrive as text nodes / arrays of text nodes). */
function textOf(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (Array.isArray(children)) return children.map(textOf).join('')
  return children == null ? '' : String(children)
}

/** CodeHighlighter hardcodes the prism `oneLight` palette and ignores antd's
 * darkAlgorithm — in dark mode inject `oneDark` via `highlightProps` (kept
 * transparent so the card's own background wins). */
function useHighlightProps() {
  const { theme } = useTheme()
  if (theme !== 'dark') return undefined
  return {
    style: {
      ...oneDark,
      'pre[class*="language-"]': {
        ...oneDark['pre[class*="language-"]'],
        background: 'transparent',
        margin: 0
      },
      'code[class*="language-"]': {
        ...oneDark['code[class*="language-"]'],
        background: 'transparent'
      }
    }
  }
}

/** Code-block header matching CodeHighlighter's built-in one (language name
 * left, copy action right) with ONE change: the copy glyph is our own
 * `copy.svg`, the same asset the assistant-bubble copy button uses.
 *
 * A custom `header` is the only way in — CodeHighlighter exposes no icon prop
 * and hardcodes `<Actions.Copy text={code} />`. `Actions.Copy` itself does take
 * an `icon`, so the built-in copy behaviour (clipboard write + copied feedback)
 * is kept as-is; only the glyph is swapped.
 *
 * The header/title class names have to be reproduced for the component's own
 * stylesheet to still apply, so the prefix is resolved the same way the
 * component resolves it — antd's `ConfigContext.getPrefixCls` (which is exactly
 * what x's internal `useXProviderContext` forwards) — rather than hardcoding
 * `ant-`, which a ConfigProvider `prefixCls` would break. */
function CodeHeader({ lang, code }: { lang: string; code: string }) {
  const { getPrefixCls } = useContext(ConfigProvider.ConfigContext)
  const prefixCls = getPrefixCls('codeHighlighter')
  return (
    <div className={`${prefixCls}-header`}>
      <span className={`${prefixCls}-header-title`}>{lang}</span>
      <Actions.Copy text={code} icon={<CopyIcon className="h-4 w-4" />} />
    </div>
  )
}

/** Fenced code blocks → CodeHighlighter (language pill + copy button);
 * ```mermaid fences → live Mermaid diagrams; inline code stays plain. */
function Code(props: ComponentProps) {
  const highlightProps = useHighlightProps()
  const className = String((props as { className?: string }).className ?? '')
  const lang = /language-(\w+)/.exec(className)?.[1]
  const body = textOf(props.children)

  if (!lang) {
    // Inline code (no language- class): keep the default element.
    return <code className={className}>{props.children}</code>
  }
  if (lang === 'mermaid') {
    // Render the diagram only once the fence is complete; while streaming,
    // show the source as a code block (avoids mermaid parse churn).
    if (props.streamStatus === 'loading') {
      return (
        <CodeHighlighter
          className="msa-code-highlighter"
          lang="mermaid"
          highlightProps={highlightProps}
          header={<CodeHeader lang="mermaid" code={body} />}
        >
          {body}
        </CodeHighlighter>
      )
    }
    return <Mermaid>{body}</Mermaid>
  }
  return (
    <CodeHighlighter
      lang={lang}
      className="msa-code-highlighter"
      highlightProps={highlightProps}
      prismLightMode={false}
      header={<CodeHeader lang={lang} code={body} />}
    >
      {body}
    </CodeHighlighter>
  )
}

/** `<mermaid>` tag emitted by x-markdown for mermaid fences → diagram. */
function MermaidTag(props: ComponentProps) {
  return <Mermaid>{textOf(props.children)}</Mermaid>
}

/** Links always open in a NEW tab. Markdown here is model output (citations,
 * search results, docs) — navigating the SPA away from a live conversation
 * would drop the user out of the chat (and can abort an in-flight turn), so
 * every link leaves the app in a separate tab instead of in place.
 * `rel="noopener noreferrer"` because the target is untrusted content. */
function Anchor(props: ComponentProps) {
  const {
    children,
    // Dropped: x-markdown injects parser metadata that is not valid DOM.
    domNode: _domNode,
    streamStatus: _streamStatus,
    lang: _lang,
    block: _block,
    ...rest
  } = props as ComponentProps & { href?: string }
  return (
    <a {...rest} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}

// Stable references (x-markdown best practice: never rebuild per render).
const COMPONENTS = {
  a: Anchor,
  code: Code,
  mermaid: MermaidTag
}
const CONFIG = { extensions: Latex() }

/**
 * Project-wide Markdown renderer. Wraps `@ant-design/x-markdown` so chat
 * messages, skill viewers, and any other consumers share a single import path
 * — making future swaps (theme tokens, plugins, custom components) one-edit
 * changes.
 *
 * Bundled capabilities (chat-oriented):
 * - GFM basics (tables, lists, links…) from x-markdown itself;
 * - fenced code → CodeHighlighter, ```mermaid → Mermaid diagrams;
 * - LaTeX math ($…$ / $$…$$) via the official Latex plugin (KaTeX);
 * - optional YAML frontmatter handling (`frontmatter` prop);
 * - light/dark typography theme following the app theme.
 */
export function Markdown({ content, streaming, frontmatter }: Props) {
  const { theme } = useTheme()
  return (
    <XMarkdown
      className={`msa-md-body ${
        theme === 'dark' ? 'x-markdown-dark' : 'x-markdown-light'
      }`}
      content={frontmatter ? withFrontmatterAsYaml(content) : content}
      components={COMPONENTS}
      config={CONFIG}
      streaming={streaming ? { hasNextChunk: true } : undefined}
    />
  )
}
