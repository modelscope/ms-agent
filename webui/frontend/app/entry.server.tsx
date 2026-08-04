import { createCache, extractStyle, StyleProvider } from '@ant-design/cssinjs'
import { createReadableStreamFromReadable } from '@react-router/node'
import { version as antdVersion } from 'antd'
import { isbot } from 'isbot'
import { Transform } from 'node:stream'
import type { RenderToPipeableStreamOptions } from 'react-dom/server'
import { renderToPipeableStream } from 'react-dom/server'
import type { EntryContext } from 'react-router'
import { ServerRouter } from 'react-router'

const STREAM_TIMEOUT = 5_000

export default function handleRequest(
  request: Request,
  responseStatusCode: number,
  responseHeaders: Headers,
  routerContext: EntryContext
) {
  return new Promise<Response>((resolve, reject) => {
    let shellRendered = false
    const userAgent = request.headers.get('user-agent')

    // Bots and SPA mode renders wait for all content; humans get a fast shell.
    // See https://react.dev/reference/react-dom/server/renderToPipeableStream
    const readyOption: keyof RenderToPipeableStreamOptions =
      (userAgent && isbot(userAgent)) || routerContext.isSpaMode
        ? 'onAllReady'
        : 'onShellReady'

    const cache = createCache()

    const { pipe, abort } = renderToPipeableStream(
      <StyleProvider cache={cache} layer>
        <ServerRouter context={routerContext} url={request.url} />
      </StyleProvider>,
      {
        [readyOption]() {
          shellRendered = true

          // Buffer the full HTML so we can inject the extracted antd styles
          // into <head> before flushing to the client. This trades streaming
          // for correct first-paint styles — antd cssinjs needs the full
          // render to know which atomic styles were used.
          const chunks: Buffer[] = []
          const transformStream = new Transform({
            transform(chunk, _encoding, callback) {
              chunks.push(chunk)
              callback()
            },
            flush(callback) {
              const html = Buffer.concat(chunks).toString('utf8')
              // cssinjs already wraps output in `@layer antd` because
              // <StyleProvider layer> is on — see the layer order in app.css
              // for why this lets Tailwind utilities win without `!important`.
              const css = extractStyle(cache, true)
              const antdTag = css
                ? `<style data-rc-order="prepend" data-rc-priority="-9999" data-antd-version="${antdVersion}">${css}</style>`
                : ''

              const out = antdTag
                ? html.replace('</head>', `${antdTag}</head>`)
                : html

              this.push(out)
              callback()
            }
          })

          responseHeaders.set('Content-Type', 'text/html')

          resolve(
            new Response(createReadableStreamFromReadable(transformStream), {
              headers: responseHeaders,
              status: responseStatusCode
            })
          )

          pipe(transformStream)
        },
        onShellError(error: unknown) {
          reject(error)
        },
        onError(error: unknown) {
          responseStatusCode = 500
          // Shell errors get rejected above and logged by the framework; only
          // log post-shell streaming errors here.
          if (shellRendered) {
            console.error(error)
          }
        }
      }
    )

    setTimeout(abort, STREAM_TIMEOUT + 1000)
  })
}
