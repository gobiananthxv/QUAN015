/** Display formatting. Null means "no defined value" and must never render as 0. */
import type { Num } from './api'

const DASH = '—'

export const pct = (v: Num, digits = 1): string =>
  v === null || !Number.isFinite(v) ? DASH : `${(v * 100).toFixed(digits)}%`

export const num = (v: Num, digits = 2): string =>
  v === null || !Number.isFinite(v) ? DASH : v.toFixed(digits)

export const money = (v: Num): string =>
  v === null || !Number.isFinite(v)
    ? DASH
    : `$${Math.round(v).toLocaleString('en-US')}`

export const int = (v: Num): string =>
  v === null || !Number.isFinite(v) ? DASH : Math.round(v).toLocaleString('en-US')

/** Green for good, red for bad — with `higherIsBetter=false` for drawdowns. */
export const signClass = (v: Num, higherIsBetter = true): string => {
  if (v === null || !Number.isFinite(v) || v === 0) return ''
  const good = higherIsBetter ? v > 0 : v < 0
  return good ? 'pos' : 'neg'
}

export const STRATEGY_COLORS: Record<string, string> = {
  sma_crossover: '#4f9cf9',
  ema_trend: '#8b5cf6',
  momentum: '#10b981',
  mean_reversion: '#f59e0b',
  buy_and_hold: '#94a3b8',
}

export const ASSET_COLORS: Record<string, string> = {
  GOLD: '#eab308',
  BTC: '#f97316',
  NVDA: '#22c55e',
}

/**
 * Recharts tooltip formatters.
 *
 * Recharts types a tooltip value as `string | number | array | undefined`, so a
 * plain `(v: number) => string` is not assignable. These wrappers accept the
 * real union and render anything non-numeric as an em dash — which is also the
 * correct behaviour for the nulls the API deliberately sends.
 */
export type TipValue = string | number | readonly (string | number)[] | undefined

const asNumber = (v: TipValue): number | null => (typeof v === 'number' ? v : null)

export const tipPct = (v: TipValue): string => pct(asNumber(v))
export const tipNum = (v: TipValue): string => num(asNumber(v))
export const tipNum0 = (v: TipValue): string => num(asNumber(v), 0)
export const tipNum3 = (v: TipValue): string => num(asNumber(v), 3)
export const tipMoney = (v: TipValue): string => money(asNumber(v))
export const tipVolume = (v: TipValue): string => int(asNumber(v))
