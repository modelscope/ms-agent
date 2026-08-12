/** Inline-code style wrapper for dynamic entities inside step card headers
 * (file paths, tool/MCP names, skill names, search queries…) — the visual
 * analog of markdown backticks, on the msa fill token so it reads on both the
 * fill-1 shell cards and the fill-2 accordion headers. */
export function InlineCode({ children }: { children: React.ReactNode }) {
  return (
    <code className="mx-0.5 rounded-md bg-msa-fill-3 px-1.5 py-0.5 align-middle font-mono text-[0.85em]">
      {children}
    </code>
  )
}
