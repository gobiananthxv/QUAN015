import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, DEFAULT_CONFIG, type Num, type Plateau, type RegimeRow, type StrategyInfo } from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { num, pct, tipPct } from '../format'

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
  const [name, setName] = useState('sma_crossover')
  const [rob, setRob] = useState<Robustness | null>(null)
  const [regime, setRegime] = useState<RegimeRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setRob(null)
    setRegime(null)
    setError(null)
    Promise.all([
      api.robustness(asset, name, DEFAULT_CONFIG),
      api.regimeAttribution(asset, name),
    ])
      .then(([r, g]) => {
        setRob(r)
        setRegime(g.rows)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [asset, name])

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

  return (
    <>
      <Panel title="Parameter surface" subtitle={`Sharpe across ${p.combinations} parameter combinations`} wide>
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
        <Note>
          <strong>Exposure</strong> is usually the revealing column. A trend
          strategy's value typically shows up as being barely invested during bear
          regimes rather than as a higher return anywhere.
        </Note>
      </Panel>
    </>
  )
}
