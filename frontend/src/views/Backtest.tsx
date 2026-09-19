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
  type Period,
  type RunResult,
  type StrategyInfo,
} from '../api'
import { ErrorState, Loading, Note, Panel, Stat } from '../components/Common'
import { describePeriod, usePeriod } from '../period'
import { Figure, Insight, type Tone } from '../components/Insight'
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
  // The backtesting period the brief asks for *is* the platform period. Two
  // controls that look alike and mean slightly different things would be worse
  // than one, so this tab reads the shared value rather than owning its own.
  const { period, bounds } = usePeriod()
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
  const runWith = (p: Record<string, number>, cfg: BacktestConfig, per: Period = period) => {
    setBusy(true)
    setError(null)
    api
      .backtest(asset, name, p, cfg, per)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  const run = () => runWith(params, config, period)

  // Selecting a strategy (or asset) resets to that strategy's defaults and runs.
  useEffect(() => {
    if (!info) return
    const defaults = { ...info.defaults }
    setParams(defaults)
    runWith(defaults, config, period)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset, name, info, period])

  const strat = result?.strategy
  const bench = result?.benchmark

  /**
   * The verdict, derived from the two result sets rather than written by hand.
   * Return and drawdown are judged separately because a strategy losing on
   * return while cutting drawdown is a trade-off, not a failure — and saying so
   * is more useful than a single thumbs up or down.
   */
  const verdict = (() => {
    if (!strat || !bench) return null
    const sr = strat.stats.total_return ?? 0
    const br = bench.stats.total_return ?? 0
    const sd = strat.stats.max_drawdown ?? 0
    const bd = bench.stats.max_drawdown ?? 0
    const wonReturn = sr > br
    const wonDrawdown = sd > bd // less negative is shallower
    const relative = (1 + sr) / (1 + br) - 1

    const tone: Tone = wonReturn && wonDrawdown ? 'good' : wonReturn || wonDrawdown ? 'caution' : 'bad'
    return { sr, br, sd, bd, wonReturn, wonDrawdown, relative, tone }
  })()

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
          <label title="Fraction of equity committed per entry. 0.5 deploys half and leaves half in cash.">
            position size %
            <input
              type="number"
              step={5}
              min={5}
              max={100}
              value={Math.round(config.position_pct * 100)}
              onChange={(e) =>
                setConfig({
                  ...config,
                  position_pct: Math.min(Math.max(Number(e.target.value), 1), 100) / 100,
                })
              }
            />
          </label>
          <label title="Allow short positions. Shorts pay a borrow fee for every bar they are held.">
            allow shorts
            <select
              value={config.allow_short ? 'yes' : 'no'}
              onChange={(e) => setConfig({ ...config, allow_short: e.target.value === 'yes' })}
            >
              <option value="no">no</option>
              <option value="yes">yes</option>
            </select>
          </label>
          {config.allow_short && (
            <label title="Annual cost of borrowing the asset, charged per bar while short.">
              borrow bps/yr
              <input
                type="number"
                step={25}
                min={0}
                value={config.borrow_bps_annual}
                onChange={(e) =>
                  setConfig({ ...config, borrow_bps_annual: Number(e.target.value) })
                }
              />
            </label>
          )}

          <button className="btn primary" onClick={run} disabled={busy}>
            {busy ? 'Running…' : 'Run backtest'}
          </button>
        </div>

        <Note>
          Running over <strong>{describePeriod(period, bounds)}</strong> — set by
          the Period bar at the top of the page, or by dragging the Overview
          chart. Signals are regenerated inside the window, so a sub-period is a
          genuine out-of-sample run rather than a trimmed full-history one.
        </Note>
        {info && <Note>{info.description}</Note>}
      </Panel>

      {error && <ErrorState error={error} onRetry={run} />}
      {busy && !result && <Loading what="the backtest" />}

      {strat && bench && verdict && (
        <>
          <Insight
            label="Verdict against buy-and-hold"
            tone={verdict.tone}
            headline={
              verdict.wonReturn ? (
                <>
                  {info?.label} <Figure value="beat" tone="good" /> buy-and-hold —{' '}
                  <Figure value={pct(verdict.sr)} /> against{' '}
                  <Figure value={pct(verdict.br)} />, ending with{' '}
                  <Figure value={pct(verdict.relative)} tone="good" /> more wealth
                  than simply holding.
                </>
              ) : (
                <>
                  {info?.label} <Figure value="lost" tone="bad" /> to buy-and-hold on
                  return — <Figure value={pct(verdict.sr)} /> against{' '}
                  <Figure value={pct(verdict.br)} />, ending with just{' '}
                  <Figure value={pct(1 + verdict.relative, 0)} tone="bad" /> of the
                  wealth simply holding would have produced.
                </>
              )
            }
          >
            {verdict.wonDrawdown ? (
              <>
                It cut the worst drawdown from <Figure value={pct(verdict.bd)} /> to{' '}
                <Figure value={pct(verdict.sd)} tone="good" />, holding a position
                only {pct(strat.stats.exposure, 0)} of the time
                {/* Only frame this as a trade-off when it actually was one. On a
                    falling market a trend filter can win on BOTH axes, and
                    calling that "lower return for lower risk" is simply wrong. */}
                {verdict.wonReturn
                  ? ' — it won on both axes here, which is what a trend filter is supposed to do in a falling market.'
                  : '. Lower return for lower risk is a different objective, not a worse one.'}
              </>
            ) : (
              <>
                And it did not compensate with a shallower drawdown either —{' '}
                <Figure value={pct(verdict.sd)} tone="bad" /> against the
                benchmark's <Figure value={pct(verdict.bd)} />. On this asset the
                strategy is worse on both axes.
              </>
            )}{' '}
            It paid {money(strat.stats.total_costs)} in commission and slippage
            across {int(strat.stats.num_trades)} trades. Check the Research tab
            before trusting any of these numbers.
          </Insight>

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
                  <Stat label="Costs paid" value={money(strat.stats.total_costs)} hint="Commission + slippage + borrow" />
                  <Stat label="Position size" value={pct(strat.config.position_pct as number, 0)} hint="Fraction of equity committed per entry" />
                </div>
              </div>
              <div>
                <h3 style={{ color: STRATEGY_COLORS.buy_and_hold }}>
                  Buy &amp; Hold{' '}
                  <span
                    className="hint-tag"
                    title="Always fully invested, whatever position size the strategy uses. A benchmark that shrank with your settings would not be a reference point. It still pays the same commission and slippage."
                  >
                    always 100% invested
                  </span>
                </h3>
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
