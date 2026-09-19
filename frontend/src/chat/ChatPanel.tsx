/**
 * Slide-over chatbot panel.
 *
 * On submit it snapshots the live dashboard state (`getPageJson`) and asks the
 * backend to route Qwen3-8B over the Featherless API. Every assistant reply is
 * rendered with a "Where this came from" context badge (page, asset, charts)
 * followed by the markdown answer. The immediately-previous exchange is sent as
 * history so follow-up questions like "and what about SMA?" keep working.
 */
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type ChatMsg } from '../api'
import { usePage } from '../page/pageContext'
import type { PageJson } from '../page/pageContext'

interface AssistantMeta {
  page_name: string
  page_id: string
  selected_asset: string
  charts: { id: string; title: string }[]
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  meta?: AssistantMeta
  error?: string
}

function ContextBadge({ meta }: { meta: AssistantMeta }) {
  return (
    <div className="chat-context">
      <span className="badge-label">Where this came from</span>
      <span>
        Sourced from page: <strong>{meta.page_name}</strong>
      </span>
      <span>
        Asset: <strong>{meta.selected_asset}</strong>
      </span>
      <span>
        Charts:{' '}
        {meta.charts.length
          ? meta.charts.map((c) => `[${c.id}]`).join(' · ')
          : 'none — ask about metrics directly'}
      </span>
    </div>
  )
}

export function ChatPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { getPageJson } = usePage()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, busy])

  const send = async () => {
    const prompt = input.trim()
    if (!prompt || busy) return

    const pageJson: PageJson = getPageJson()
    const history: ChatMsg[] = messages.slice(-2).map((m) => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content,
    }))

    setMessages((m) => [...m, { role: 'user', content: prompt }])
    setInput('')
    setBusy(true)
    try {
      const { reply } = await api.chat({
        page_json: pageJson as unknown as Record<string, unknown>,
        user_prompt: prompt,
        history,
      })
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: reply,
          meta: {
            page_name: pageJson.page_name,
            page_id: pageJson.page_id,
            selected_asset: pageJson.selected_asset,
            charts: pageJson.charts.map((c) => ({ id: c.id, title: c.title })),
          },
        },
      ])
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err)
      setMessages((m) => [...m, { role: 'assistant', content: '', error: detail }])
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <>
      <div className={`chat-backdrop${open ? ' open' : ''}`} onClick={onClose} />
      <aside
        className={`chat-panel${open ? ' open' : ''}`}
        role="dialog"
        aria-label="QMAFIB chatbot"
        aria-hidden={!open}
      >
        <header className="chat-header">
          <div>
            <h2>Chatbot</h2>
            <p>Qwen3-8B · answers use the live dashboard page</p>
          </div>
          <button className="btn" onClick={onClose} aria-label="Close chatbot">
            ✕
          </button>
        </header>

        <div className="chat-history" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chat-placeholder">
              <p>Ask about the current page, for example:</p>
              <p>
                <em>“Based on this page, give the overall view.”</em>
              </p>
              <p>
                <em>
                  “What is this drawdown chart trying to say?”
                </em>
              </p>
              <p>
                <em>“What are the dependencies of SMA?”</em>
              </p>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="chat-msg user">
                <div className="bubble">{m.content}</div>
              </div>
            ) : (
              <div key={i} className="chat-msg assistant">
                {m.meta && <ContextBadge meta={m.meta} />}
                <div className="bubble">
                  {m.error ? (
                    <p className="chat-error">{m.error}</p>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  )}
                </div>
              </div>
            ),
          )}

          {busy && (
            <div className="chat-msg assistant">
              <div className="bubble chat-typing">Thinking…</div>
            </div>
          )}
        </div>

        <form
          className="chat-input"
          onSubmit={(e) => {
            e.preventDefault()
            void send()
          }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about this page…"
            rows={2}
            disabled={busy}
          />
          <button className="btn primary" type="submit" disabled={busy || !input.trim()}>
            Send
          </button>
        </form>
      </aside>
    </>
  )
}