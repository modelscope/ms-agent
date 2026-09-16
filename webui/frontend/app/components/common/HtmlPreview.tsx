interface Props {
  /** Raw-bytes URL of the HTML file. */
  src: string
  /** Accessible name — the file's path. */
  title: string
  /** Change to reload the frame (the document on disk was rewritten). */
  reloadKey?: string | number
}

/**
 * Preview of an HTML file: an iframe pointed at the file's raw-bytes URL, so
 * the browser resolves the document's own relative styles, scripts and images
 * itself — against that same route, which is why the path sits in the URL tail.
 *
 * `sandbox` without `allow-same-origin`: the document is agent output or an
 * upload, yet it is served from our origin. Scripts stay on (a preview without
 * them is not the page), but the opaque origin keeps them away from the app's
 * cookies, storage and API. The backend sends the equivalent CSP for anyone who
 * opens the raw URL directly.
 */
export function HtmlPreview({ src, title, reloadKey }: Props) {
  return (
    <iframe
      key={reloadKey}
      src={src}
      title={title}
      sandbox="allow-scripts allow-forms allow-popups allow-modals"
      className="h-full w-full border-none bg-white"
    />
  )
}
