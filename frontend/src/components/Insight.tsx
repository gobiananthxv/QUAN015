import type { ReactNode } from 'react'

/**
 * The headline finding for a view.
 *
 * Every Insight on this dashboard is **computed from the data on screen**, never
 * written as static copy. A table of 40 numbers does not tell a reader what to
 * look at; this does, and it stays true when the data is refreshed or the asset
 * is switched.
 *
 * `tone` carries the judgement so the reader gets it before reading a word:
 *   good     — the result favours the strategy or the asset
 *   caution  — true but easy to misread, or a risk worth naming
 *   bad      — the result is unfavourable and we are not hiding it
 *   neutral  — context, no verdict
 */
export type Tone = 'good' | 'caution' | 'bad' | 'neutral'

const ICON: Record<Tone, string> = {
  good: '▲',
  caution: '!',
  bad: '▼',
  neutral: '•',
}

export function Insight({
  label,
  headline,
  tone = 'neutral',
  children,
}: {
  /** Short kicker, e.g. "What this shows". */
  label: string
  /** The finding itself, in one sentence. Computed, not hardcoded. */
  headline: ReactNode
  tone?: Tone
  /** Optional second sentence: why it matters, or the caveat. */
  children?: ReactNode
}) {
  return (
    <aside className={`insight ${tone}`}>
      <span className="insight-icon" aria-hidden="true">{ICON[tone]}</span>
      <div className="insight-body">
        <span className="insight-label">{label}</span>
        <p className="insight-headline">{headline}</p>
        {children && <p className="insight-detail">{children}</p>}
      </div>
    </aside>
  )
}

/** A number pulled out of a sentence so the eye lands on it. */
export function Figure({ value, tone }: { value: string; tone?: Tone }) {
  return <strong className={`figure${tone ? ' ' + tone : ''}`}>{value}</strong>
}
