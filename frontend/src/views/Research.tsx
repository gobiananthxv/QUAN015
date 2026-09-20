import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  api,
  DEFAULT_CONFIG,
  type Num,
  type Plateau,
  type RegimeForecast,
  type RegimeRow,
  type StrategyInfo,
} from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { describePeriod, usePeriod } from '../period'
import { Figure, Insight, type Tone } from '../components/Insight'
import type { ChartDescriptor } from '../page/pageContext'
import { useRegisterCharts } from '../page/pageContext'
import { num, pct, tipPct } from '../format'

const REGIME_COLORS: Record<string, string> = {
  Bull: '#22c55e',          // Emerald green
  Bear: '#ef4444',          // Crimson red
  'High-Volatility': '#f59e0b', // Amber
  Sideways: '#3b82f6',      // Electric blue
  Transitional: '#a855f7',  // Vivid violet purple
  Unknown: '#a855f7',       // Fallback
}

const REGIME_BG: Record<string, string> = {
  Bull: 'rgba(34, 197, 94, 0.15)',
  Bear: 'rgba(239, 68, 68, 0.15)',
  'High-Volatility': 'rgba(245, 158, 11, 0.15)',
  Sideways: 'rgba(59, 130, 246, 0.15)',
  Transitional: 'rgba(168, 85, 247, 0.15)',
  Unknown: 'rgba(168, 85, 247, 0.15)',
}

const FALLBACK_COLORS = ['#22c55e', '#ef4444', '#f59e0b', '#3b82f6', '#a855f7', '#06b6d4', '#ec4899', '#14b8a6']

const FORECAST_DURATIONS = [21, 30, 60, 90, 120, 180]

type ForecastViewMode = 'area' | 'lines' | 'confidence'

function ForecastTooltip({
  active,
  payload,
  label,
  regimes,
  horizon,
}: {
  active?: boolean
  payload?: Array<{ dataKey: string; value: number; color?: string; name?: string }>
  label?: number | string
  regimes: string[]
  horizon: number
}) {
  if (!active || !payload || !payload.length) return null
  const day = Number(label)
  const isInformative = horizon > 0 ? day <= horizon : true

  const sorted = [...payload]
    .filter((p) => regimes.includes(String(p.dataKey)))
    .sort((a, b) => Number(b.value) - Number(a.value))

  const top = sorted[0]

  return (
    <div
      style={{
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: 8,
        padding: '10px 14px',
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)',
        minWidth: 220,
        fontSize: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #1e293b',
          paddingBottom: 6,
          marginBottom: 8,
          gap: 12,
        }}
      >
        <span style={{ fontWeight: 600, color: '#f8fafc' }}>
          Day {day}{' '}
          <small style={{ color: '#64748b', fontWeight: 400 }}>
            (~{Math.max(1, Math.round(day / 21))} mo ahead)
          </small>
        </span>
        <span
          style={{
            fontSize: 10,
            padding: '2px 6px',
            borderRadius: 4,
            fontWeight: 600,
            background: isInformative ? 'rgba(34, 197, 94, 0.15)' : 'rgba(148, 163, 184, 0.15)',
            color: isInformative ? '#4ade80' : '#94a3b8',
            border: `1px solid ${isInformative ? 'rgba(34, 197, 94, 0.3)' : 'rgba(148, 163, 184, 0.2)'}`,
          }}
        >
          {isInformative ? '● Active Signal' : '○ Stationary'}
        </span>
      </div>

      {top && (
        <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: '#94a3b8', fontSize: 11 }}>Dominant:</span>
          <span
            style={{
              fontWeight: 600,
              color: REGIME_COLORS[top.dataKey] ?? '#38bdf8',
              background: REGIME_BG[top.dataKey] ?? 'rgba(56, 189, 248, 0.12)',
              padding: '1px 6px',
              borderRadius: 4,
              fontSize: 11,
            }}
          >
            {top.dataKey} ({pct(Number(top.value), 1)})
          </span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {sorted.map((item) => {
          const val = Number(item.value)
          const color = REGIME_COLORS[item.dataKey] ?? item.color ?? '#38bdf8'
          return (
            <div key={item.dataKey} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#cbd5e1' }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: color,
                      display: 'inline-block',
                    }}
                  />
                  {item.dataKey}
                </span>
                <strong style={{ color: '#f8fafc', fontVariantNumeric: 'tabular-nums' }}>
                  {pct(val, 1)}
                </strong>
              </div>
              <div
                style={{
                  width: '100%',
                  height: 3,
                  background: '#1e293b',
                  borderRadius: 2,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: `${Math.min(100, Math.max(0, val * 100))}%`,
                    height: '100%',
                    background: color,
                    borderRadius: 2,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DecayTooltip({
  active,
  payload,
  label,
  horizon,
}: {
  active?: boolean
  payload?: Array<{ dataKey: string; value: number; color?: string; name?: string }>
  label?: number | string
  horizon: number
}) {
  if (!active || !payload || !payload.length) return null
  const day = Number(label)
  const isInformative = horizon > 0 ? day <= horizon : true

  return (
    <div
      style={{
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: 8,
        padding: '10px 14px',
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5)',
        minWidth: 190,
        fontSize: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #1e293b',
          paddingBottom: 6,
          marginBottom: 8,
        }}
      >
        <span style={{ fontWeight: 600, color: '#f8fafc' }}>Day {day}</span>
        <span
          style={{
            fontSize: 10,
            padding: '2px 6px',
            borderRadius: 4,
            fontWeight: 600,
            background: isInformative ? 'rgba(34, 197, 94, 0.15)' : 'rgba(148, 163, 184, 0.15)',
            color: isInformative ? '#4ade80' : '#94a3b8',
          }}
        >
          {isInformative ? 'Active Signal' : 'Stationary'}
        </span>
      </div>
      {payload.map((p) => (
        <div
          key={p.dataKey}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 12,
            marginBottom: 4,
            fontSize: 11,
          }}
        >
          <span style={{ color: '#94a3b8' }}>{p.name ?? p.dataKey}:</span>
          <strong style={{ color: p.color ?? '#f8fafc' }}>
            {p.dataKey === 'max_prob' ? pct(p.value, 1) : num(p.value, 3)}
          </strong>
        </div>
      ))}
    </div>
  )
}

type Robustness = Awaited<ReturnType<typeof api.robustness>>


/** Sharpe heat colouring: red below zero, green above, intensity by magnitude. */
function cell(v: Num, best: number): string {
  if (v === null) return '#1e293b'
  if (v <= 0) return `rgba(239, 68, 68, ${0.15 + Math.min(Math.abs(v), 1) * 0.5})`
  return `rgba(34, 197, 94, ${0.1 + (v / Math.max(best, 0.01)) * 0.7})`
}

function verdictClass(verdict: string): string {
  if (verdict.startsWith('robust')) return 'badge good'
  if (verdict.startsWith('moderate')) return 'badge warn'
  return 'badge bad'
}

export function Research({ asset, strategies }: { asset: string; strategies: StrategyInfo[] }) {
  const { period, bounds } = usePeriod()
  const [name, setName] = useState('sma_crossover')
  const [rob, setRob] = useState<Robustness | null>(null)
  const [regime, setRegime] = useState<RegimeRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [forecastDays, setForecastDays] = useState(60)
  const [forecast, setForecast] = useState<RegimeForecast | null>(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastError, setForecastError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ForecastViewMode>('area')
  const [activeRegime, setActiveRegime] = useState<string | null>(null)

  const load = () => {
    setRob(null)
    setRegime(null)
    setError(null)
    Promise.all([
      api.robustness(asset, name, DEFAULT_CONFIG, period),
      api.regimeAttribution(asset, name, period),
    ])
      .then(([r, g]) => {
        setRob(r)
        setRegime(g.rows)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [asset, name, period])

  useEffect(() => {
    setForecastLoading(true)
    setForecastError(null)
    api
      .regimeForecast(asset, forecastDays, period)
      .then(setForecast)
      .catch((e) => setForecastError(e.message))
      .finally(() => setForecastLoading(false))
  }, [asset, forecastDays, period])

  useRegisterCharts(
    useMemo<ChartDescriptor[]>(() => {
      if (!rob || !regime) return []
      const p = rob.plateau
      const label = strategies.find((s) => s.name === name)?.label ?? name
      const beatCount = rob.periods.filter((w) => Number(w.relative_return) > 0).length
      const firstNegativeCost = rob.costs.find((c) => Number(c.total_return) < 0)
      const row = (r: RegimeRow) => ({
        regime: r.regime,
        days: r.days,
        exposure: r.exposure,
        strategy_return: r.strategy_return,
        benchmark_return: r.benchmark_return,
        relative_return: r.relative_return,
        beat_benchmark: r.beat_benchmark,
      })
      const descriptors: ChartDescriptor[] = [
        {
          id: 'robustness_plateau',
          title: `${label} — Robustness Research`,
          chart_type: 'surface',
          formula: `Sharpe across a ${rob.axes.x} x ${rob.axes.y} parameter grid; robustness = median Sharpe / best cell`,
          data_source: 'Backend /robustness (dozens of backtests over the selected period)',
          result: {
            asset,
            strategy: name,
            period: describePeriod(period, bounds),
            axes: rob.axes,
            combinations: p.combinations,
            verdict: p.verdict,
            best: p.best,
            median: p.median,
            worst: p.worst,
            spread: p.spread,
            share_positive: p.share_positive,
            robustness: p.robustness,
            best_params: p.best_params,
            beat_windows: `${beatCount} of ${rob.periods.length}`,
            first_negative_cost_bps: firstNegativeCost ? Number(firstNegativeCost.bps_per_side) : null,
          },
        },
        {
          id: 'regime_attribution',
          title: `${label} — Regime Attribution`,
          chart_type: 'summary',
          formula:
            'Strategy vs benchmark, split by trend and volatility regimes (exposure, return, excess)',
          data_source: 'Backend /regime-attribution',
          result: {
            trend: regime.filter((r) => r.axis === 'trend').map(row),
            volatility: regime.filter((r) => r.axis === 'volatility').map(row),
          },
        },
      ]
      if (forecast) {
        descriptors.push({
          id: 'regime_forecast',
          title: `${asset} — Regime Forecast`,
          chart_type: 'forecast',
          formula: 'p(n) = p0 · T^n via HMM transition matrix; horizon is conservative bound where signal exceeds random/stationary',
          data_source: 'Backend /forecast/regime',
          result: {
            asset: forecast.asset,
            ticker: forecast.ticker,
            current_regime: forecast.current_regime,
            n_states: forecast.n_states,
            horizon: forecast.horizon,
            stationary: forecast.stationary,
            days: forecast.days,
            top_regime_at_horizon:
              forecast.decay.find((d) => d.day === forecast.horizon.conservative)?.top_regime ??
              forecast.current_regime,
          },
        })
      }
      return descriptors
    }, [strategies, asset, name, period, bounds, rob, regime, forecast]),
  )


  const selector = (
    <div className="controls inline">
      <label>
        Strategy
        <select value={name} onChange={(e) => setName(e.target.value)}>
          {strategies.map((s) => (
            <option key={s.name} value={s.name}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )

  if (error) return <><Panel title="Research" wide>{selector}</Panel><ErrorState error={error} onRetry={load} /></>
  if (!rob || !regime)
    return (
      <>
        <Panel title="Research" wide>{selector}</Panel>
        <Loading what="parameter sweeps — this runs dozens of backtests" />
      </>
    )

  const p: Plateau = rob.plateau
  const xs = [...new Set(rob.surface.map((c) => c.x))].sort((a, b) => a - b)
  const ys = [...new Set(rob.surface.map((c) => c.y))].sort((a, b) => a - b)
  const grid = new Map(rob.surface.map((c) => [`${c.x}|${c.y}`, c.sharpe]))
  const best = p.best ?? 1

  const trend = regime.filter((r) => r.axis === 'trend')
  const vol = regime.filter((r) => r.axis === 'volatility')

  // The verdict string already encodes the judgement; map it to a tone.
  const tone: Tone = p.verdict.startsWith('robust')
    ? 'good'
    : p.verdict.startsWith('moderate')
      ? 'caution'
      : 'bad'

  const bull = trend.find((r) => r.regime === 'bull')
  const bear = trend.find((r) => r.regime === 'bear')
  const beatCount = rob.periods.filter((w) => Number(w.relative_return) > 0).length
  const firstNegativeCost = rob.costs.find((c) => Number(c.total_return) < 0)

  return (
    <>
      <Insight
        label="Should you believe this backtest?"
        tone={tone}
        headline={
          tone === 'good' ? (
            <>
              Robust. <Figure value={pct(p.share_positive, 0)} tone="good" /> of{' '}
              {p.combinations} parameter combinations are profitable, and the
              median Sharpe of <Figure value={num(p.median)} /> sits close to the
              best cell's <Figure value={num(p.best)} />.
            </>
          ) : tone === 'caution' ? (
            <>
              Mixed. The result holds across much of the grid but is sensitive to
              parameters — median Sharpe <Figure value={num(p.median)} /> against a
              best of <Figure value={num(p.best)} />.
            </>
          ) : (
            <>
              <Figure value="Treat with suspicion." tone="bad" /> The result is
              concentrated in a few cells: median Sharpe{' '}
              <Figure value={num(p.median)} tone="bad" /> against a best of{' '}
              <Figure value={num(p.best)} />, with only{' '}
              <Figure value={pct(p.share_positive, 0)} /> of combinations
              profitable.
            </>
          )
        }
      >
        {tone === 'good'
          ? 'A flat surface means the parameter choice barely matters, so the result is not an artefact of tuning.'
          : 'A single bright cell surrounded by poor ones is what over-fitting looks like. Pick a different strategy, or accept that this one was lucky on this history.'}{' '}
        {beatCount * 2 < rob.periods.length ? (
          <>
            But a stable surface is not the same as a reliable edge: split into{' '}
            {rob.periods.length} independent windows, it beat buy-and-hold in only{' '}
            <Figure value={`${beatCount}`} tone="bad" /> of them
          </>
        ) : (
          <>
            It also holds up over time, beating buy-and-hold in{' '}
            <Figure value={`${beatCount} of ${rob.periods.length}`} tone="good" />{' '}
            independent windows
          </>
        )}
        {firstNegativeCost ? (
          <>
            , and it turns unprofitable once costs reach{' '}
            <Figure value={`${Number(firstNegativeCost.bps_per_side)} bps`} tone="bad" />{' '}
            per side.
          </>
        ) : (
          ', and it stays profitable at every cost level tested.'
        )}
      </Insight>

      <Panel
        title="Parameter surface"
        subtitle={`${describePeriod(period, bounds)} · Sharpe across ${p.combinations} parameter combinations`}
        wide
      >
        {selector}
        <table className="heatmap">
          <thead>
            <tr>
              <th>{rob.axes.y} \ {rob.axes.x}</th>
              {xs.map((x) => <th key={x}>{x}</th>)}
            </tr>
          </thead>
          <tbody>
            {ys.map((y) => (
              <tr key={y}>
                <th>{y}</th>
                {xs.map((x) => {
                  const v = grid.get(`${x}|${y}`) ?? null
                  const isBest =
                    p.best_params[rob.axes.x] === x && p.best_params[rob.axes.y] === y
                  return (
                    <td key={x} style={{ background: cell(v, best) }} className={isBest ? 'best-cell' : ''}>
                      {num(v)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>

        <div className="verdict">
          <span className={verdictClass(p.verdict)}>{p.verdict}</span>
          <div className="stats compact">
            <div className="stat"><span className="stat-label">best</span><span className="stat-value">{num(p.best)}</span></div>
            <div className="stat"><span className="stat-label">median</span><span className="stat-value">{num(p.median)}</span></div>
            <div className="stat"><span className="stat-label">worst</span><span className="stat-value">{num(p.worst)}</span></div>
            <div className="stat"><span className="stat-label">positive cells</span><span className="stat-value">{pct(p.share_positive, 0)}</span></div>
            <div className="stat"><span className="stat-label">robustness</span><span className="stat-value">{num(p.robustness)}</span></div>
          </div>
        </div>
        <Note>
          <strong>Robustness</strong> is the median Sharpe across the whole grid
          divided by the best cell. Near 1 means the surface is flat and the
          parameter choice barely matters — the result is not an artefact of
          tuning. Near 0 means a single cell carries everything, which is the
          signature of over-fitting. Reporting the surface instead of its maximum
          is the point.
        </Note>
      </Panel>

      <Panel title="Cost sensitivity" subtitle="An edge that only exists at zero cost is not an edge">
        <ResponsiveContainer width="100%" height={230}>
          <LineChart data={rob.costs} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="bps_per_side" tick={{ fontSize: 11 }} stroke="#64748b" label={{ value: 'bps per side', position: 'insideBottom', offset: -2, fontSize: 11, fill: '#64748b' }} />
            <YAxis tickFormatter={(v) => pct(v, 0)} tick={{ fontSize: 11 }} stroke="#64748b" />
            <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }} formatter={tipPct} />
            <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="3 3" />
            <Line dataKey="total_return" name="total return" stroke="#4f9cf9" strokeWidth={1.6} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Period stability" subtitle="Geometric excess vs buy-and-hold, per window">
        <ResponsiveContainer width="100%" height={230}>
          <BarChart data={rob.periods} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="start" tick={{ fontSize: 10 }} stroke="#64748b" />
            <YAxis tickFormatter={(v) => pct(v, 0)} tick={{ fontSize: 11 }} stroke="#64748b" />
            <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }} formatter={tipPct} />
            <ReferenceLine y={0} stroke="#64748b" />
            <Bar dataKey="relative_return" name="excess vs benchmark" fill="#8b5cf6" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
        <Note>
          Geometric, not a difference of totals: −70% means the strategy ended the
          window with 30% of the benchmark's wealth. A strategy that only wins in
          one window found an episode, not an edge.
        </Note>
      </Panel>

      <Panel title="Regime attribution" subtitle="Where the strategy earns its keep" wide>
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Axis</th><th>Regime</th><th>Days</th><th>Exposure</th>
                <th>Strategy</th><th>Benchmark</th><th>Excess</th><th>Beat?</th>
              </tr>
            </thead>
            <tbody>
              {[...trend, ...vol].map((r) => (
                <tr key={`${r.axis}-${r.regime}`}>
                  <td>{r.axis}</td>
                  <td><code>{r.regime}</code></td>
                  <td>{r.days.toLocaleString()}</td>
                  <td><strong>{pct(r.exposure, 0)}</strong></td>
                  <td className={(r.strategy_return ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(r.strategy_return)}</td>
                  <td className={(r.benchmark_return ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(r.benchmark_return)}</td>
                  <td className={(r.relative_return ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(r.relative_return)}</td>
                  <td>{r.beat_benchmark ? '✓' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {bull && bear && (
          <Insight
            label="Where the strategy earns its keep"
            tone={Number(bear.exposure) < Number(bull.exposure) ? 'good' : 'caution'}
            headline={
              <>
                It held a position <Figure value={pct(bear.exposure, 0)} /> of the
                time in bear regimes against{' '}
                <Figure value={pct(bull.exposure, 0)} /> in bull regimes — losing{' '}
                <Figure value={pct(bear.strategy_return)} /> where the benchmark
                lost <Figure value={pct(bear.benchmark_return)} tone="bad" />.
              </>
            }
          >
            <strong>Exposure</strong> is the revealing column, not return. A trend
            strategy's value shows up as being absent when the market falls, which
            is exactly what it is for — now measured rather than asserted.
          </Insight>
        )}
      </Panel>

      <Panel
        title="Regime forecast"
        subtitle={`HMM predictive transition matrix · next ${forecastDays} trading days`}
        wide
      >
        {forecast && (
          <div className="stats" style={{ marginBottom: 16 }}>
            <div className="stat">
              <span className="stat-label">Current Regime</span>
              <span
                className="stat-value"
                style={{
                  color: REGIME_COLORS[forecast.current_regime] ?? '#38bdf8',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <span
                  style={{
                    width: 9,
                    height: 9,
                    borderRadius: '50%',
                    background: REGIME_COLORS[forecast.current_regime] ?? '#38bdf8',
                  }}
                />
                {forecast.current_regime}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Predictive Horizon</span>
              <span className="stat-value" style={{ color: '#38bdf8' }}>
                ~{forecast.horizon.conservative} d{' '}
                <small style={{ fontSize: 11, color: '#64748b', fontWeight: 400 }}>
                  ({Math.max(1, Math.round(forecast.horizon.conservative / 5))} wks)
                </small>
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Outlook @ Horizon</span>
              <span
                className="stat-value"
                style={{
                  color:
                    REGIME_COLORS[
                      forecast.decay.find((d) => d.day === forecast.horizon.conservative)?.top_regime ??
                        forecast.current_regime
                    ] ?? '#38bdf8',
                  fontSize: 14,
                }}
              >
                {forecast.decay.find((d) => d.day === forecast.horizon.conservative)?.top_regime ??
                  forecast.current_regime}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Markov Structure</span>
              <span className="stat-value">{forecast.n_states} States</span>
            </div>
          </div>
        )}

        <div
          style={{
            marginBottom: 16,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
            background: 'var(--panel-alt)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '10px 14px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              style={{
                fontSize: 11,
                color: '#94a3b8',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                fontWeight: 600,
              }}
            >
              Duration
            </span>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {FORECAST_DURATIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  className={`chip${forecastDays === d ? ' active' : ''}`}
                  onClick={() => setForecastDays(d)}
                >
                  {d}d
                </button>
              ))}
            </div>
            <label
              style={{
                fontSize: 11,
                color: '#64748b',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                marginLeft: 4,
              }}
            >
              Custom:
              <select
                value={forecastDays}
                onChange={(e) => setForecastDays(Number(e.target.value))}
                style={{ padding: '3px 8px', fontSize: 12 }}
              >
                {FORECAST_DURATIONS.map((d) => (
                  <option key={d} value={d}>
                    {d} trading days (~{Math.round(d / 21)} mo)
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
              View
            </span>
            <div
              style={{
                display: 'flex',
                gap: 4,
                background: 'var(--panel)',
                padding: 3,
                borderRadius: 6,
                border: '1px solid var(--border)',
              }}
            >
              <button
                type="button"
                className={`chip${viewMode === 'area' ? ' active' : ''}`}
                style={{ fontSize: 11, padding: '4px 10px' }}
                onClick={() => setViewMode('area')}
              >
                Distribution (Area)
              </button>
              <button
                type="button"
                className={`chip${viewMode === 'lines' ? ' active' : ''}`}
                style={{ fontSize: 11, padding: '4px 10px' }}
                onClick={() => setViewMode('lines')}
              >
                Trajectories
              </button>
              <button
                type="button"
                className={`chip${viewMode === 'confidence' ? ' active' : ''}`}
                style={{ fontSize: 11, padding: '4px 10px' }}
                onClick={() => setViewMode('confidence')}
              >
                Signal Quality
              </button>
            </div>
          </div>
        </div>

        {forecast && forecast.regimes.length > 0 && (
          <div
            style={{
              marginBottom: 12,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 8,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, color: '#64748b' }}>Highlight:</span>
              {forecast.regimes.map((reg) => {
                const isSel = activeRegime === reg
                const color = REGIME_COLORS[reg] ?? '#94a3b8'
                return (
                  <button
                    key={reg}
                    type="button"
                    className={`chip${isSel ? ' active' : ''}`}
                    style={{
                      borderColor: isSel ? color : undefined,
                      background: isSel ? color : undefined,
                      color: isSel ? '#041022' : undefined,
                      fontSize: 11,
                      padding: '3px 8px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                    }}
                    onClick={() => setActiveRegime(isSel ? null : reg)}
                  >
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        background: isSel ? '#041022' : color,
                      }}
                    />
                    {reg}
                  </button>
                )
              })}
              {activeRegime && (
                <button
                  type="button"
                  className="chip reset"
                  style={{ padding: '2px 8px', fontSize: 11 }}
                  onClick={() => setActiveRegime(null)}
                >
                  ✕ Clear
                </button>
              )}
            </div>

            <div style={{ fontSize: 11, color: '#64748b', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 2, background: '#38bdf8', display: 'inline-block' }} />
              <span>Dashed line marks statistical signal horizon</span>
            </div>
          </div>
        )}

        {forecastLoading && !forecast && <Loading what="future regime prediction" />}
        {forecastError && <ErrorState error={forecastError} />}
        {forecast && (
          <>
            <ResponsiveContainer width="100%" height={340}>
              {viewMode === 'confidence' ? (
                <LineChart data={forecast.decay} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                  <CartesianGrid stroke="#1e293b" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11 }}
                    stroke="#64748b"
                    label={{
                      value: 'Trading Days Ahead',
                      position: 'insideBottom',
                      offset: -2,
                      fontSize: 11,
                      fill: '#64748b',
                    }}
                  />
                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(v) => pct(v, 0)}
                    tick={{ fontSize: 11 }}
                    stroke="#64748b"
                  />
                  <Tooltip content={<DecayTooltip horizon={forecast.horizon.conservative} />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {forecast.horizon.conservative > 0 &&
                    forecast.horizon.conservative <= forecast.days && (
                      <ReferenceLine
                        x={forecast.horizon.conservative}
                        stroke="#38bdf8"
                        strokeDasharray="3 3"
                        label={{
                          value: `Horizon ~${forecast.horizon.conservative}d`,
                          fill: '#38bdf8',
                          fontSize: 11,
                          position: 'insideTopLeft',
                        }}
                      />
                    )}
                  <ReferenceLine
                    y={1 / forecast.n_states + 0.1}
                    stroke="#f59e0b"
                    strokeDasharray="3 3"
                    label={{
                      value: `Informative Threshold (${pct(1 / forecast.n_states + 0.1, 0)})`,
                      fill: '#f59e0b',
                      fontSize: 10,
                      position: 'insideBottomRight',
                    }}
                  />
                  <Line
                    dataKey="max_prob"
                    name="Max Regime Probability"
                    stroke="#22c55e"
                    strokeWidth={2.4}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    dataKey="kl_div"
                    name="KL Divergence (nats)"
                    stroke="#06b6d4"
                    strokeWidth={1.8}
                    strokeDasharray="4 4"
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              ) : viewMode === 'lines' ? (
                <LineChart data={forecast.rows} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                  <CartesianGrid stroke="#1e293b" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11 }}
                    stroke="#64748b"
                    label={{
                      value: 'Trading Days Ahead',
                      position: 'insideBottom',
                      offset: -2,
                      fontSize: 11,
                      fill: '#64748b',
                    }}
                  />
                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(v) => pct(v, 0)}
                    tick={{ fontSize: 11 }}
                    stroke="#64748b"
                  />
                  <Tooltip
                    content={
                      <ForecastTooltip
                        regimes={forecast.regimes}
                        horizon={forecast.horizon.conservative}
                      />
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {forecast.horizon.conservative > 0 &&
                    forecast.horizon.conservative <= forecast.days && (
                      <ReferenceLine
                        x={forecast.horizon.conservative}
                        stroke="#38bdf8"
                        strokeDasharray="3 3"
                        label={{
                          value: `Horizon ~${forecast.horizon.conservative}d`,
                          fill: '#38bdf8',
                          fontSize: 11,
                          position: 'insideTopLeft',
                        }}
                      />
                    )}
                  {forecast.regimes.map((reg, idx) => {
                    const color = REGIME_COLORS[reg] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
                    const isFocus = activeRegime === reg
                    const isDimmed = activeRegime !== null && !isFocus
                    return (
                      <Line
                        key={reg}
                        type="monotone"
                        dataKey={reg}
                        name={reg}
                        stroke={color}
                        strokeWidth={isFocus ? 3.5 : 2}
                        strokeOpacity={isDimmed ? 0.2 : 1}
                        dot={false}
                        isAnimationActive={false}
                      />
                    )
                  })}
                </LineChart>
              ) : (
                <AreaChart data={forecast.rows} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                  <defs>
                    {forecast.regimes.map((reg, idx) => {
                      const color = REGIME_COLORS[reg] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
                      const isFocus = activeRegime === reg
                      const isDimmed = activeRegime !== null && !isFocus
                      return (
                        <linearGradient key={`grad-${reg}`} id={`grad-${reg}`} x1="0" y1="0" x2="0" y2="1">
                          <stop
                            offset="5%"
                            stopColor={color}
                            stopOpacity={isDimmed ? 0.15 : isFocus ? 0.95 : 0.82}
                          />
                          <stop
                            offset="95%"
                            stopColor={color}
                            stopOpacity={isDimmed ? 0.05 : isFocus ? 0.6 : 0.42}
                          />
                        </linearGradient>
                      )
                    })}
                  </defs>
                  <CartesianGrid stroke="#1e293b" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 11 }}
                    stroke="#64748b"
                    label={{
                      value: 'Trading Days Ahead',
                      position: 'insideBottom',
                      offset: -2,
                      fontSize: 11,
                      fill: '#64748b',
                    }}
                  />
                  <YAxis
                    domain={[0, 1]}
                    tickFormatter={(v) => pct(v, 0)}
                    tick={{ fontSize: 11 }}
                    stroke="#64748b"
                  />
                  <Tooltip
                    content={
                      <ForecastTooltip
                        regimes={forecast.regimes}
                        horizon={forecast.horizon.conservative}
                      />
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {forecast.horizon.conservative > 0 &&
                    forecast.horizon.conservative <= forecast.days && (
                      <>
                        <ReferenceArea
                          x1={1}
                          x2={forecast.horizon.conservative}
                          fill="#38bdf8"
                          fillOpacity={0.03}
                        />
                        <ReferenceLine
                          x={forecast.horizon.conservative}
                          stroke="#38bdf8"
                          strokeDasharray="3 3"
                          label={{
                            value: `Horizon ~${forecast.horizon.conservative}d`,
                            fill: '#38bdf8',
                            fontSize: 11,
                            position: 'insideTopLeft',
                          }}
                        />
                      </>
                    )}
                  {forecast.regimes.map((reg, idx) => {
                    const color = REGIME_COLORS[reg] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
                    const isFocus = activeRegime === reg
                    const isDimmed = activeRegime !== null && !isFocus
                    return (
                      <Area
                        key={reg}
                        type="monotone"
                        dataKey={reg}
                        name={reg}
                        stackId="1"
                        stroke={color}
                        strokeWidth={isFocus ? 2.5 : 1}
                        fill={`url(#grad-${reg})`}
                        fillOpacity={isDimmed ? 0.2 : 1}
                        isAnimationActive={false}
                      />
                    )
                  })}
                </AreaChart>
              )}
            </ResponsiveContainer>

            <div
              style={{
                marginTop: 16,
                padding: '12px 16px',
                background: 'var(--panel-alt)',
                borderRadius: 8,
                border: '1px solid var(--border)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 8,
                  flexWrap: 'wrap',
                  gap: 8,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#94a3b8',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}
                >
                  Long-Run Stationary Distribution (Convergence As \(n \to \infty\))
                </span>
                <span style={{ fontSize: 11, color: '#64748b' }}>
                  Unconditional base rates where Markov chain settles
                </span>
              </div>
              <div
                style={{
                  display: 'flex',
                  height: 10,
                  borderRadius: 5,
                  overflow: 'hidden',
                  background: '#1e293b',
                  marginBottom: 10,
                }}
              >
                {forecast.regimes.map((r) => {
                  const share = forecast.stationary[r] ?? 0
                  if (share <= 0) return null
                  return (
                    <div
                      key={r}
                      style={{
                        width: `${share * 100}%`,
                        background: REGIME_COLORS[r] ?? '#94a3b8',
                        height: '100%',
                      }}
                      title={`${r}: ${pct(share, 1)}`}
                    />
                  )
                })}
              </div>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {forecast.regimes.map((r) => (
                  <span key={r} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: REGIME_COLORS[r] ?? '#94a3b8',
                      }}
                    />
                    <span style={{ color: '#94a3b8' }}>{r}:</span>
                    <strong style={{ color: '#f8fafc' }}>
                      {pct(forecast.stationary[r] ?? 0, 1)}
                    </strong>
                  </span>
                ))}
              </div>
            </div>

            <Note>
              Future regime distributions are derived from the Hidden Markov Model transition
              matrix \(p(n) = p_0 \cdot T^n\). The <strong>Transitional</strong> regime captures
              structural shift states where asset returns and volatility fluctuate between established
              macro regimes. Within the <strong>predictive horizon</strong> (~
              {forecast.horizon.conservative} trading days), the forecast carries active statistical
              edge over random chance; beyond this window, distributions converge toward long-run stationary base rates.
            </Note>
          </>
        )}
      </Panel>
    </>
  )
}


