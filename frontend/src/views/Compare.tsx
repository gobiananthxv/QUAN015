import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, DEFAULT_CONFIG, type RunResult, type StrategyInfo } from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { Figure, Insight, type Tone } from '../components/Insight'
import { money, num, pct, STRATEGY_COLORS, tipMoney } from '../format'

type Result = { asset: string; runs: RunResult[]; benchmark: RunResult }

/**
 * All four strategies against one benchmark, on one chart.
 *
 * Every run uses the same asset, the same capital and the same costs, so the
 * comparison is like-for-like — including the benchmark, which is simulated
 * through the same engine and pays the same entry cost.
 */
export function Compare({ asset, strategies }: { asset: string; strategies: StrategyInfo[] }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState<'equity' | 'drawdown'>('equity')

  const load = () => {
    setData(null)
    setError(null)
    api.compare(asset, DEFAULT_CONFIG).then(setData).catch((e) => setError(e.message))
  }

  useEffect(load, [asset])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!data) return <Loading what="four strategies and the benchmark" />

  const label = (name: string) =>
    strategies.find((s) => s.name === name)?.label ?? name

  const all = [...data.runs, data.benchmark]
  const dates = data.benchmark.curves.dates
  const series = dates.map((date, i) => {
    const row: Record<string, string | number | null> = { date }
    for (const run of all) {
      row[run.strategy] =
        metric === 'equity' ? run.curves.equity[i] : run.curves.drawdown[i]
    }
    return row
  })

  // Rank on the metric a reader cares about, and say plainly who won.
  const benchReturn = data.benchmark.stats.total_return ?? 0
  const ranked = [...data.runs].sort(
    (a, b) => (b.stats.total_return ?? 0) - (a.stats.total_return ?? 0),
  )
  const best = ranked[0]
  const beaters = data.runs.filter((r) => (r.stats.total_return ?? 0) > benchReturn)
  const shallower = data.runs.filter(
    (r) => (r.stats.max_drawdown ?? 0) > (data.benchmark.stats.max_drawdown ?? 0),
  )
  const tone: Tone = beaters.length ? 'good' : shallower.length ? 'caution' : 'bad'

  const axis = { tick: { fontSize: 11 }, stroke: '#64748b' }

  return (
    <>
      <Insight
        label={`All strategies on ${asset}`}
        tone={tone}
        headline={
          beaters.length ? (
            <>
              <Figure value={`${beaters.length} of ${data.runs.length}`} tone="good" />{' '}
              {beaters.length === 1 ? 'strategy beat' : 'strategies beat'} buy-and-hold
              on return — best is {label(best.strategy)} at{' '}
              <Figure value={pct(best.stats.total_return)} /> against the benchmark's{' '}
              <Figure value={pct(benchReturn)} />.
            </>
          ) : (
            <>
              <Figure value="None" tone="bad" /> of the {data.runs.length} strategies
              beat buy-and-hold on return. The best, {label(best.strategy)}, returned{' '}
              <Figure value={pct(best.stats.total_return)} /> against the benchmark's{' '}
              <Figure value={pct(benchReturn)} />.
            </>
          )
        }
      >
        {shallower.length > 0 && (
          <>
            <Figure value={`${shallower.length}`} /> of them did cut the worst
            drawdown below the benchmark's{' '}
            <Figure value={pct(data.benchmark.stats.max_drawdown)} tone="bad" />
            {' '}— which is the trade trend-following actually offers on a decade
            that trended this hard.{' '}
          </>
        )}
        All five runs use identical capital and costs, and the benchmark pays the
        same entry commission and slippage as every strategy.
      </Insight>

      <Panel
        title={`${asset} — every strategy against buy-and-hold`}
        subtitle={`$${DEFAULT_CONFIG.initial_capital.toLocaleString()} · ${DEFAULT_CONFIG.commission_bps} bps commission · ${DEFAULT_CONFIG.slippage_bps} bps slippage`}
        wide
      >
        <div className="controls inline">
          <label>
            Show
            <select value={metric} onChange={(e) => setMetric(e.target.value as 'equity' | 'drawdown')}>
              <option value="equity">Equity curve</option>
              <option value="drawdown">Drawdown</option>
            </select>
          </label>
        </div>

        <ResponsiveContainer width="100%" height={360}>
          <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} {...axis} />
            <YAxis
              scale={metric === 'equity' ? 'log' : 'auto'}
              domain={metric === 'equity' ? ['auto', 'auto'] : [(d: number) => d, 0]}
              tickFormatter={(v) => (metric === 'equity' ? money(v) : pct(v, 0))}
              {...axis}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
              formatter={metric === 'equity' ? tipMoney : ((v: unknown) => (typeof v === 'number' ? pct(v) : '—'))}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {all.map((run) => (
              <Line
                key={run.strategy}
                dataKey={run.strategy}
                name={run.strategy === 'buy_and_hold' ? 'Buy & Hold' : label(run.strategy)}
                stroke={STRATEGY_COLORS[run.strategy] ?? '#94a3b8'}
                strokeWidth={run.strategy === 'buy_and_hold' ? 1.4 : 1.6}
                strokeDasharray={run.strategy === 'buy_and_hold' ? '4 3' : undefined}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <Note>
          {metric === 'equity'
            ? 'Log scale — over a decade a linear axis hides everything before the final two years.'
            : 'Distance below each run’s own running peak. Closer to zero is better.'}
        </Note>
      </Panel>

      <Panel title="Ranked by total return" wide>
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Strategy</th><th>Total</th><th>CAGR</th><th>Sharpe</th>
                <th>Max DD</th><th>Trades</th><th>Win %</th><th>Exposure</th><th>Costs</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r) => (
                <tr key={r.strategy}>
                  <td>
                    <span className="swatch" style={{ background: STRATEGY_COLORS[r.strategy] }} />
                    {label(r.strategy)}
                  </td>
                  <td className={(r.stats.total_return ?? 0) > benchReturn ? 'pos' : ''}>
                    {pct(r.stats.total_return)}
                  </td>
                  <td>{pct(r.stats.cagr)}</td>
                  <td>{num(r.stats.sharpe)}</td>
                  <td className={
                    (r.stats.max_drawdown ?? 0) > (data.benchmark.stats.max_drawdown ?? 0) ? 'pos' : ''
                  }>
                    {pct(r.stats.max_drawdown)}
                  </td>
                  <td>{num(r.stats.num_trades, 0)}</td>
                  <td>{pct(r.stats.win_rate, 0)}</td>
                  <td>{pct(r.stats.exposure, 0)}</td>
                  <td>{money(r.stats.total_costs)}</td>
                </tr>
              ))}
              <tr className="benchmark-row">
                <td>
                  <span className="swatch" style={{ background: STRATEGY_COLORS.buy_and_hold }} />
                  Buy &amp; Hold
                </td>
                <td>{pct(benchReturn)}</td>
                <td>{pct(data.benchmark.stats.cagr)}</td>
                <td>{num(data.benchmark.stats.sharpe)}</td>
                <td>{pct(data.benchmark.stats.max_drawdown)}</td>
                <td>—</td>
                <td>—</td>
                <td>{pct(data.benchmark.stats.exposure, 0)}</td>
                <td>{money(data.benchmark.stats.total_costs)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Note>
          Green marks a figure that beats the benchmark. A strategy can win on
          drawdown while losing on return — those are different objectives, and
          the table shows both rather than collapsing them into a ranking.
        </Note>
      </Panel>
    </>
  )
}
