import type { ReactNode } from 'react'
import type { Num } from '../api'
import { signClass } from '../format'

export function Panel({
  title,
  subtitle,
  children,
  wide,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  wide?: boolean
}) {
  return (
    <section className={`panel${wide ? ' wide' : ''}`}>
      <header>
        <h2>{title}</h2>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </header>
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  raw,
  higherIsBetter = true,
  hint,
}: {
  label: string
  value: string
  raw?: Num
  higherIsBetter?: boolean
  hint?: string
}) {
  return (
    <div className="stat" title={hint}>
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${raw === undefined ? '' : signClass(raw, higherIsBetter)}`}>
        {value}
      </span>
    </div>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="state">
      <div className="spinner" />
      <p>Computing {what}…</p>
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="state error">
      <p><strong>Something went wrong</strong></p>
      <p className="detail">{error}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn">
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ message }: { message: string }) {
  return <div className="state"><p>{message}</p></div>
}

/** A short caption explaining what a chart means, so the view is self-documenting. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="note">{children}</p>
}
