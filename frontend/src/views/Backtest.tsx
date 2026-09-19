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

// Parameters that are fractions rather than bar counts, so a step of 1 would be
// useless. Kept as data because the alternative is a growing chain of string
// tests inside the render.
const SMALL_STEP = new Set(['band', 'threshold'])
const COARSE_STEP = new Set(['target_vol', 'cap', 'floor'])
// Parameters that describe the asset's trading calendar, not the strategy's
// behaviour. The backend fills them from the asset registry, so sending the
// catalogue's generic default would override a correct value with a wrong one
// on BTC. They are dropped rather than shown read-only: an input nobody should
// touch is still an input somebody will.
const CALENDAR_PARAMS = new Set(['ann_factor'])

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
  // A strategy that exposes a `cap` is one that sizes continuously, which is
  // the only kind that can lever up or rebalance often enough for a band to
  // matter. Detecting it from the parameters keeps the panel generic instead of
  // naming a specific strategy in the UI layer.
  const sizes = 'cap' in params
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
    const defaults = Object.fromEntries(
      Object.entries(info.defaults).filter(([k]) => !CALENDAR_PARAMS.has(k)),
    )
    setParams(defaults)
    runWith(defaults, config, period)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset, name, info, period])

  const strat = result?.strategy
  const bench = result?.benchmark
  // Same test as `sizes`, but against the result rather than the form. They
  // differ for the moment between picking a strategy and its run returning,
  // and reading leverage stats off a run that has none would render blanks.
  const ranSizing = !!strat && 'cap' in strat.params

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
                step={SMALL_STEP.has(k) || k.includes('z') ? 0.005 : COARSE_STEP.has(k) ? 0.05 : 1}
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
          {sizes && (
            <>
              <label title="Annual interest on borrowed cash, charged for every bar exposure sits above 100%. Institutions fund near 5%; retail margin is often 8-12%. Raise it until the strategy stops winning — that tells you what rate the result depends on.">
                financing bps/yr
                <input
                  type="number"
                  step={50}
                  min={0}
                  value={config.financing_bps_annual}
                  onChange={(e) =>
                    setConfig({ ...config, financing_bps_annual: Number(e.target.value) })
                  }
                />
              </label>
              <label title="Smallest change in target size worth trading, as a share of the position already held. A continuously-sized strategy would otherwise rebalance every single bar and pay commission for it.">
                no-trade band %
                <input
                  type="number"
                  step={5}
                  min={0}
                  max={100}
                  value={Math.round(config.no_trade_band * 100)}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      no_trade_band: Math.min(Math.max(Number(e.target.value), 0), 100) / 100,
                    })
                  }
                />
              </label>
            </>
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
                <Figure value={pct(verdict.sd)} tone="good" />
                {/* "only 99% of the time" reads as a contradiction. A strategy
                    that reduces risk by sizing down is doing something
                    different from one that reduces it by staying out, and the
                    sentence has to say which. */}
                {ranSizing ? (
                  <>
                    {' '}
                    without ever leaving the market — it sized down instead,
                    averaging {pct(strat.stats.avg_leverage, 0)} of equity
                  </>
                ) : (
                  <>, holding a position only {pct(strat.stats.exposure, 0)} of the time</>
                )}
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
            {/* A continuously-sized strategy may never close a position, so
                "across 0 trades" would be both true and useless. Count what it
                actually did instead. */}
            It paid {money(strat.stats.total_costs)} in friction across{' '}
            {ranSizing
              ? `${int(strat.stats.total_rebalances)} rebalances`
              : `${int(strat.stats.num_trades)} trades`}
            {ranSizing && Number(strat.stats.total_financing) > 0 && (
              <>
                , of which {money(strat.stats.total_financing)} was interest on
                borrowed cash at {num(Number(strat.config.financing_bps_annual) / 100, 1)}% a
                year
              </>
            )}
            . Check the Research tab before trusting any of these numbers.
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
                  {/* Both are computed over *closed* trades. With none closed
                      they are 0.0, and a 0% win rate reads as "it lost every
                      trade" rather than "it has not finished one yet". */}
                  <Stat
                    label="Win rate"
                    value={Number(strat.stats.num_trades) > 0 ? pct(strat.stats.win_rate) : '—'}
                    hint={Number(strat.stats.num_trades) > 0 ? undefined : 'No closed trades yet — the position is still open'}
                  />
                  <Stat
                    label="Profit factor"
                    value={Number(strat.stats.num_trades) > 0 ? num(strat.stats.profit_factor) : '—'}
                    hint="Gross wins / gross losses across closed trades. Blank when there were no losing trades, or none have closed."
                  />
                  <Stat label="Exposure" value={pct(strat.stats.exposure)} hint="Share of days holding a position" />
                  <Stat label="Costs paid" value={money(strat.stats.total_costs)} hint="Commission + slippage + borrow" />
                  {ranSizing ? (
                    <>
                      <Stat label="Avg size" value={pct(strat.stats.avg_leverage, 0)} hint="Average target exposure while invested. Above 100% is borrowed." />
                      <Stat label="Peak size" value={pct(strat.stats.max_leverage, 0)} hint="Largest exposure it ever held. If this equals the cap, the cap is binding and the result depends on it." />
                      <Stat label="Rebalances" value={int(strat.stats.total_rebalances)} hint="Times the position was resized without being closed" />
                      <Stat label="Financing" value={money(strat.stats.total_financing)} hint="Interest paid on borrowed cash" />
                    </>
                  ) : (
                    <Stat label="Position size" value={pct(strat.config.position_pct as number, 0)} hint="Fraction of equity committed per entry" />
                  )}
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

          <Panel title="Trade log" subtitle={`${strat.trades?.length ?? 0} ${strat.trades?.length === 1 ? 'trade' : 'trades'}`} wide>
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
