import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Renders model output as Markdown and turns [n] citations into interactive
 * chips that highlight the matching source.
 */
export default function Markdown({ text, sources = [], onCite, streaming }) {
  const withCites = (text || '').replace(/\[(\d{1,3})\](?!\()/g, '[$1](#cite-$1)')
  const byN = Object.fromEntries(sources.map((s) => [s.n, s]))

  return (
    <div className={`markdown ${streaming ? 'streaming' : ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) {
            if (href?.startsWith('#cite-')) {
              const n = Number(href.slice(6))
              const src = byN[n]
              return (
                <button
                  type="button"
                  className={`cite ${src ? '' : 'cite-missing'}`}
                  title={src ? src.title : 'Unknown source'}
                  onClick={() => src && onCite?.(n)}
                >
                  {n}
                </button>
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {withCites}
      </ReactMarkdown>
    </div>
  )
}
