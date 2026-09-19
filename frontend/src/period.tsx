import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Period } from './api'

/**
 * One analysis period, shared by every tab.
 *
 * The alternative — a zoom control per chart — sounds more flexible and is
 * worse. Eight charts each at a different window cannot be compared against
 * each other: you cannot read a drawdown against a correlation if they are
 * showing different years. A single period means every number on screen
 * describes the same stretch of history, whichever tab you are on.
 *
 * It also removes a duplicate control. The Backtest tab needed its own date
 * range to satisfy the brief's "backtesting periods"; that range *is* this
 * period, so there is one place to set it rather than two that look alike and
 * mean slightly different things.
 *
 * `{}` means the full history. Dates are ISO `YYYY-MM-DD`, matching the API.
 */
interface PeriodState {
  period: Period
  setPeriod: (p: Period) => void
  /** Earliest and latest bar available, from the data snapshot. */
  bounds: Period
  /** True when the period is anything other than the full history. */
  restricted: boolean
}

const Ctx = createContext<PeriodState>({
  period: {},
  setPeriod: () => {},
  bounds: {},
  restricted: false,
})

export function PeriodProvider({ bounds, children }: { bounds: Period; children: ReactNode }) {
  const [period, setPeriod] = useState<Period>({})
  const value = useMemo(
    () => ({
      period,
      setPeriod,
      bounds,
      restricted: Boolean(period.start || period.end),
    }),
    [period, bounds],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const usePeriod = () => useContext(Ctx)

/**
 * Trailing-window presets.
 *
 * Measured back from the snapshot's last bar, not from today. The snapshot is
 * a committed file that may be days old; "last 1 year" should mean the final
 * year of data we actually hold, not a window that runs past the end of it.
 */
export function presetsFor(bounds: Period): { label: string; period: Period }[] {
  const end = bounds.end
  if (!end) return [{ label: 'All', period: {} }]

  const back = (years: number, months = 0) => {
    const d = new Date(`${end}T00:00:00Z`)
    d.setUTCFullYear(d.getUTCFullYear() - years)
    d.setUTCMonth(d.getUTCMonth() - months)
    return d.toISOString().slice(0, 10)
  }

  return [
    { label: 'All', period: {} },
    { label: '5Y', period: { start: back(5), end } },
    { label: '3Y', period: { start: back(3), end } },
    { label: '1Y', period: { start: back(1), end } },
    { label: '6M', period: { start: back(0, 6), end } },
    { label: '3M', period: { start: back(0, 3), end } },
  ]
}

/** Human label for the current period, for panel subtitles. */
export function describePeriod(period: Period, bounds: Period): string {
  if (!period.start && !period.end) {
    return bounds.start && bounds.end ? `full history · ${bounds.start} → ${bounds.end}` : 'full history'
  }
  return `${period.start ?? bounds.start ?? '…'} → ${period.end ?? bounds.end ?? '…'}`
}

/** Two periods are the same window. */
export function samePeriod(a: Period, b: Period): boolean {
  return (a.start ?? '') === (b.start ?? '') && (a.end ?? '') === (b.end ?? '')
}
