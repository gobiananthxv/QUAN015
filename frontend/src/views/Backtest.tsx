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
import {
  api,
  DEFAULT_CONFIG,
  type BacktestConfig,
  type RunResult,
  type StrategyInfo,
} from '../api'
import { ErrorState, Loading, Note, Panel, Stat } from '../components/Common'
import { int, money, num, pct, tipMoney, STRATEGY_COLORS } from '../format'

export function Backtest({
  asset,
  strategies,
}: {
  asset: string
  strategies: StrategyInfo[]
}) {
  const [name, setName] = useState('sma_crossover')
  const [params, setParams] = useState<Record<string, number>>({})
  const [config, setConfig] = useState<BacktestConfig>(DEFAULT_CONFIG)
  const [result, setResult] = useState<{ strategy: RunResult; benchmark: RunResult } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const info = strategies.find((s) => s.name === name)

  /**
   * `runWith` takes the parameters explicitly rather than reading component
   * state. Reading state here would race on mount: the effect below sets the
   * defaults and immediately runs, but `params` would still hold the previous
   * render's value, so the first backtest never fired.
   */
  const runWith = (p: Record<string, number>, cfg: BacktestConfig) => {
    setBusy(true)
    setError(null)
    api
      .backtest(asset, name, p, cfg)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  const run = () => runWith(params, config)

  // Selecting a strategy (or asset) resets to that strategy's defaults and runs.
  useEffect(() => {
    if (!info) return
    const defaults = { ...info.defaults }
    setParams(defaults)
    runWith(defaults, config)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset, name, info])

  const strat = result?.strategy
  const bench = result?.benchmark

  const equity =
    strat && bench
      ? strat.curves.dates.map((date, i) => ({
          date,
          strategy: strat.curves.equity[i],
          benchmark: bench.curves.equity[i],
        }))
      : []

  return (
    <>
      <Panel title="Configuration" wide>
        <div className="controls">
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

          {Object.entries(params).map(([k, v]) => (
            <label key={k}>
              {k}
              <input
                type="number"
                step={k.includes('z') || k === 'band' || k === 'threshold' ? 0.005 : 1}
                value={v}
                onChange={(e) => setParams({ ...params, [k]: Number(e.target.value) })}
              />
            </label>
          ))}

          <label>
            capital
            <input
              type="number"
              step={10000}
              value={config.initial_capital}
              onChange={(e) => setConfig({ ...config, initial_capital: Number(e.target.value) })}
            />
          </label>
          <label>
            commission bps
            <input
              type="number"
              step={1}
              value={config.commission_bps}
              onChange={(e) => setConfig({ ...config, commission_bps: Number(e.target.value) })}
            />
          </label>
          <label>
            slippage bps
            <input
              type="number"
              step={1}
              value={config.slippage_bps}
              onChange={(e) => setConfig({ ...config, slippage_bps: Number(e.target.value) })}
            />
          </label>

          <button className="btn primary" onClick={run} disabled={busy}>
            {busy ? 'Running…' : 'Run backtest'}
          </button>
        </div>
        {info && <Note>{info.description}</Note>}
      </Panel>

      {error && <ErrorState error={error} onRetry={run} />}
      {busy && !result && <Loading what="the backtest" />}

      {strat && bench && (
        <>
          <Panel title="Strategy vs benchmark" subtitle="Both pay the same costs" wide>
            <div className="compare">
              <div>
                <h3 style={{ color: STRATEGY_COLORS[strat.strategy] }}>{info?.label}</h3>
                <div className="stats">
                  <Stat label="Total return" value={pct(strat.stats.total_return)} raw={strat.stats.total_return} />
                  <Stat label="CAGR" value={pct(strat.stats.cagr)} raw={strat.stats.cagr} />
                  <Stat label="Sharpe" value={num(strat.stats.sharpe)} raw={strat.stats.sharpe} />
                  <Stat label="Max drawdown" value={pct(strat.stats.max_drawdown)} raw={strat.stats.max_drawdown} higherIsBetter={false} />
                  <Stat label="Final equity" value={money(strat.stats.final_equity)} />
                  <Stat label="Trades" value={int(strat.stats.num_trades)} />
                  <Stat label="Win rate" value={pct(strat.stats.win_rate)} />
                  <Stat label="Profit factor" value={num(strat.stats.profit_factor)} hint="Gross wins / gross losses. Blank when there were no losing trades." />
                  <Stat label="Exposure" value={pct(strat.stats.exposure)} hint="Share of days holding a position" />
                  <Stat label="Costs paid" value={money(strat.stats.total_costs)} />
                </div>
              </div>
              <div>
                <h3 style={{ color: STRATEGY_COLORS.buy_and_hold }}>Buy &amp; Hold</h3>
                <div className="stats">
                  <Stat label="Total return" value={pct(bench.stats.total_return)} raw={bench.stats.total_return} />
                  <Stat label="CAGR" value={pct(bench.stats.cagr)} raw={bench.stats.cagr} />
                  <Stat label="Sharpe" value={num(bench.stats.sharpe)} raw={bench.stats.sharpe} />
                  <Stat label="Max drawdown" value={pct(bench.stats.max_drawdown)} raw={bench.stats.max_drawdown} higherIsBetter={false} />
                  <Stat label="Final equity" value={money(bench.stats.final_equity)} />
                  <Stat label="Costs paid" value={money(bench.stats.total_costs)} />
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="Equity curve" wide>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={equity} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                <CartesianGrid stroke="#1e293b" vertical={false} />
                <XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} stroke="#64748b" />
                <YAxis scale="log" domain={['auto', 'auto']} tick={{ fontSize: 11 }} stroke="#64748b" tickFormatter={(v) => money(v)} />
                <Tooltip
                  contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
                  formatter={tipMoney}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="strategy" name={info?.label} stroke={STRATEGY_COLORS[strat.strategy]} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                <Line dataKey="benchmark" name="Buy & Hold" stroke={STRATEGY_COLORS.buy_and_hold} dot={false} strokeWidth={1.3} strokeDasharray="4 3" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title="Trade log" subtitle={`${strat.trades?.length ?? 0} trades`} wide>
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th>Entry</th><th>Exit</th><th>Units</th><th>In</th><th>Out</th>
                    <th>Gross</th><th>Costs</th><th>Net</th><th>Return</th><th>Bars</th>
                  </tr>
                </thead>
                <tbody>
                  {(strat.trades ?? []).map((t, i) => (
                    <tr key={i} className={t.is_open ? 'open-trade' : ''}>
                      <td>{t.entry_date}</td>
                      <td>{t.exit_date ?? 'open'}</td>
                      <td>{num(t.units, 4)}</td>
                      <td>{num(t.entry_price)}</td>
                      <td>{num(t.exit_price)}</td>
                      <td>{money(t.gross_pnl)}</td>
                      <td>{money(t.costs)}</td>
                      <td className={(t.net_pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{money(t.net_pnl)}</td>
                      <td className={(t.return_pct ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(t.return_pct)}</td>
                      <td>{t.bars_held}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Note>
              Every entry fills at the <strong>next bar's open</strong> after the
              signal, paying commission and slippage. Gross P&amp;L is measured at
              unslipped prices so that net = gross − costs holds exactly.
            </Note>
          </Panel>
        </>
      )}
    </>
  )
}
