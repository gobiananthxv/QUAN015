/**
 * Typed client for the QMAFIB API.
 *
 * Every numeric field is `number | null` rather than `number`. That is not
 * defensive padding: the backend deliberately sends `null` where a value is
 * genuinely undefined — indicator warm-up periods, Sortino with no losing day,
 * profit factor with no losing trade. Charts must skip those points rather than
 * plot them as zero.
 */

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Num = number | null

export interface Asset {
  key: string
  name: string
  ticker: string
  asset_class: string
  ann_factor: number
}

export interface SnapshotEntry {
  asset: string
  name: string
  ticker: string
  available: boolean
  rows?: number
  start?: string
  end?: string
}

export interface RefreshResult {
  updated: { asset: string; rows: number; start: string; end: string }[]
  /** Assets fetched within the last day — daily bars cannot have changed. */
  skipped: { asset: string; age_hours: number; reason: string }[]
  failed: { asset: string; error: string }[]
  snapshot: SnapshotEntry[]
}

export interface StrategyInfo {
  name: string
  label: string
  description: string
  params: Record<string, number>
  defaults: Record<string, number>
}

export interface Bar {
  date: string
  open: Num
  high: Num
  low: Num
  close: Num
  volume: Num
  [key: string]: string | Num
}

export interface Summary {
  total_return: Num
  cagr: Num
  volatility: Num
  sharpe: Num
  sortino: Num
  calmar: Num
  max_drawdown: Num
  max_drawdown_duration: Num
  positive_days: Num
  [key: string]: Num
}

export interface BacktestStats extends Summary {
  initial_capital: Num
  final_equity: Num
  num_trades: Num
  num_open_trades: Num
  win_rate: Num
  profit_factor: Num
  total_costs: Num
  total_commission: Num
  total_slippage: Num
  total_borrow: Num
  total_financing: Num
  total_rebalances: Num
  exposure: Num
  avg_bars_held: Num
  /** Average target exposure while invested. 1.0 is fully invested, above that is borrowed. */
  avg_leverage: Num
  max_leverage: Num
}

export interface Curves {
  dates: string[]
  equity: Num[]
  cumulative_return: Num[]
  drawdown: Num[]
  position: number[]
}

export interface Trade {
  entry_date: string
  exit_date: string | null
  direction: string
  units: Num
  max_units: Num
  rebalances: number
  entry_price: Num
  exit_price: Num
  commission: Num
  slippage: Num
  borrow: Num
  financing: Num
  costs: Num
  gross_pnl: Num
  net_pnl: Num
  return_pct: Num
  bars_held: number
  is_open: boolean
}

export interface RunResult {
  asset: string
  strategy: string
  params: Record<string, number>
  config: Record<string, number | boolean>
  stats: BacktestStats
  curves: Curves
  trades?: Trade[]
}

export interface BacktestConfig {
  initial_capital: number
  commission_bps: number
  slippage_bps: number
  /** Fraction of equity committed per entry, 0-1. */
  position_pct: number
  allow_short: boolean
  /** Annual borrow fee charged per bar while a short is open. */
  borrow_bps_annual: number
  /** Annual interest on borrowed cash, charged whenever exposure exceeds 100%. */
  financing_bps_annual: number
  /** Minimum change in target exposure, relative to what is held, before trading. */
  no_trade_band: number
}

export const DEFAULT_CONFIG: BacktestConfig = {
  initial_capital: 100000,
  commission_bps: 10,
  slippage_bps: 5,
  position_pct: 1,
  allow_short: false,
  borrow_bps_annual: 50,
  financing_bps_annual: 500,
  no_trade_band: 0.1,
}

/** Backtest window. Omitting both ends means the full history. */
export interface Period {
  start?: string
  end?: string
}

export interface Plateau {
  metric: string
  combinations: number
  best_params: Record<string, number>
  best: Num
  median: Num
  worst: Num
  spread: Num
  share_positive: Num
  robustness: Num
  neighbour_mean: Num
  best_vs_neighbours: Num
  verdict: string
}

export interface RegimeRow {
  axis: string
  regime: string
  days: number
  share_of_period: Num
  exposure: Num
  strategy_return: Num
  strategy_sharpe: Num
  benchmark_return: Num
  benchmark_sharpe: Num
  excess_return: Num
  relative_return: Num
  beat_benchmark: boolean
}

class ApiError extends Error {
  // Declared and assigned explicitly: TypeScript's `erasableSyntaxOnly` mode
  // (the Vite default) disallows constructor parameter properties.
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${BASE}. Is the backend running?`)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  health: () => request<{ status: string; disclaimer: string }>('/health'),

  assets: () => request<{ assets: Asset[]; snapshot: SnapshotEntry[] }>('/api/assets'),

  /** The only call that reaches the market-data provider. */
  refreshData: (assets: string[] = [], force = false) =>
    post<RefreshResult>('/api/data/refresh', { assets, force }),

  strategies: () => request<{ strategies: StrategyInfo[] }>('/api/strategies'),

  ohlcv: (asset: string) =>
    request<{ asset: string; rows: number; bars: Bar[] }>(`/api/ohlcv?asset=${asset}`),

  indicators: (asset: string, smaFast = 20, smaSlow = 50, emaFast = 12, emaSlow = 26) =>
    request<{ asset: string; columns: string[]; rows: Bar[] }>(
      `/api/indicators?asset=${asset}&sma_fast=${smaFast}&sma_slow=${smaSlow}` +
        `&ema_fast=${emaFast}&ema_slow=${emaSlow}`,
    ),

  metrics: (asset: string, period: Period = {}) =>
    request<{
      asset: string
      ann_factor: number
      bars: number
      period: Period
      summary: Summary
      cumulative: { date: string; cum: Num }[]
      drawdown: { date: string; dd: Num }[]
      rolling_vol: { date: string; vol: Num }[]
      rolling_returns: { date: string; ret: Num }[]
      return_window: number
    }>(
      `/api/metrics?asset=${asset}` +
        (period.start ? `&start=${period.start}` : '') +
        (period.end ? `&end=${period.end}` : ''),
    ),

  correlation: (window = 90, period: Period = {}) =>
    request<{
      assets: string[]
      observations: number
      matrix: { a: string; b: string; value: Num }[]
      window: number
      rolling: Record<string, string | Num>[]
    }>(
      `/api/correlation?window=${window}` +
        (period.start ? `&start=${period.start}` : '') +
        (period.end ? `&end=${period.end}` : ''),
    ),

  regime: (asset: string) =>
    request<{ asset: string; rows: { date: string; trend_regime: string | null }[] }>(
      `/api/regime?asset=${asset}`,
    ),

  backtest: (
    asset: string,
    strategy: string,
    params: Record<string, number>,
    config: BacktestConfig,
    period: Period = {},
  ) =>
    post<{ strategy: RunResult; benchmark: RunResult; period: Period }>('/api/backtest', {
      asset,
      strategy,
      params,
      config,
      ...period,
    }),

  compare: (asset: string, config: BacktestConfig, period: Period = {}) =>
    post<{ asset: string; runs: RunResult[]; benchmark: RunResult; period: Period }>(
      '/api/backtest/compare',
      { asset, config, ...period },
    ),

  robustness: (asset: string, strategy: string, config: BacktestConfig, period: Period = {}) =>
    post<{
      asset: string
      strategy: string
      axes: { x: string; y: string }
      surface: { x: number; y: number; sharpe: Num }[]
      plateau: Plateau
      costs: Record<string, Num>[]
      periods: Record<string, Num | string>[]
    }>('/api/backtest/robustness', { asset, strategy, config, ...period }),

  regimeAttribution: (asset: string, strategy: string, period: Period = {}) =>
    request<{ rows: RegimeRow[] }>(
      `/api/backtest/regime-attribution?asset=${asset}&strategy=${strategy}` +
        (period.start ? `&start=${period.start}` : '') +
        (period.end ? `&end=${period.end}` : ''),
    ),
}

export { ApiError }
