import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  api,
  DEFAULT_CONFIG,
  type Bar as OhlcBar,
  type Summary,
  type Trade,
} from '../api'
import { ErrorState, Loading, Note, Panel, Stat } from '../components/Common'
import { usePeriod } from '../period'
import { Figure, Insight } from '../components/Insight'
import { int, money, num, pct, tipNum, tipVolume } from '../format'

/**
 * Moving-average periods scaled to the window being viewed.
 *
 * A 50/200 crossover produces four fills in a decade — zoom to three months and
 * there is nothing to see. The periods therefore track the window, so there are
 * always markers to inspect at whatever scale you are looking at.
 *
 * The short tiers matter more than they look: at 20 bars a 3/10 crossover finds
 * roughly two fills across all three assets, while 2/6 finds seven. The slow
 * period has to leave usable bars after its own warm-up.
 *
 * This is a *display* choice for the price chart, not a claim that these are
 * good parameters. The Backtest and Research tabs are where parameters get
 * chosen and judged; here they exist so the chart has something to show.
 */
function adaptiveParams(bars: number): { fast: number; slow: number } {
  if (bars > 1500) return { fast: 50, slow: 200 }
  if (bars > 750) return { fast: 20, slow: 100 }
  if (bars > 350) return { fast: 10, slow: 50 }
  if (bars > 150) return { fast: 5, slow: 20 }
  if (bars > 60) return { fast: 3, slow: 10 }
  return { fast: 2, slow: 6 }
}

/**
 * Smallest window the chart will zoom to.
 *
 * Below roughly a trading month two things break at once: the crossover's
 * warm-up eats the window so no markers survive, and annualising a handful of
 * daily returns produces figures that look spectacular and mean nothing — a
 * five-bar window reports a Sharpe of 23. Refusing the zoom is more honest than
 * rendering that.
 */
const MIN_WINDOW_BARS = 20

/** Below this, annualised statistics are too noisy to read as signal. */
const THIN_WINDOW_BARS = 60

type Row = {
  date: string
  close: number | null
  sma50: number | null
  sma200: number | null
  ema50: number | null
  volume: number | null
}

export function Overview({ asset }: { asset: string }) {
  // Dragging the chart sets the platform-wide period, so a selection made here
  // carries to Risk, Correlation, Backtest, Compare and Research. The chart is
  // the most natural place to choose a period; it just should not be the only
  // place that knows about it.
  const { period, setPeriod } = usePeriod()
  const [rows, setRows] = useState<OhlcBar[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Drag-to-zoom state: the two x-axis labels under the pointer.
  const [dragFrom, setDragFrom] = useState<string | null>(null)
  const [dragTo, setDragTo] = useState<string | null>(null)

  // Everything recomputed by the backend for the visible window.
  const [windowStats, setWindowStats] = useState<{
    summary: Summary
    bars: number
    trades: Trade[]
    params: { fast: number; slow: number }
  } | null>(null)
  const [windowBusy, setWindowBusy] = useState(false)
  // The window we currently want data for. A response is accepted only if it
  // still matches — safer than a monotonic request counter, which rejects a
  // valid response whenever the effect happens to fire more than once (React
  // StrictMode does exactly that in development).
  const wanted = useRef<string>('')

  useEffect(() => {
    setRows(null)
    setError(null)
    setWindowStats(null)
    api
      .indicators(asset, 50, 200, 20, 50)
      .then((ind) => setRows(ind.rows))
      .catch((e) => setError(e.message))
  }, [asset])

  const data: Row[] = useMemo(() => {
    if (!rows) return []
    return rows
      .filter((r) => r.sma_200 !== null)
      .map((r) => ({
        date: String(r.date),
        close: r.close as number | null,
        sma50: r.sma_50 as number | null,
        sma200: r.sma_200 as number | null,
        ema50: r.ema_50 as number | null,
        volume: r.volume as number | null,
      }))
  }, [rows])

  const lastIndex = Math.max(data.length - 1, 0)

  // The index window is derived from the shared period rather than held
  // separately, so there is exactly one source of truth for "what am I looking
  // at" and the chart cannot drift from the rest of the platform.
  const view = useMemo(() => {
    if (!data.length) return { start: 0, end: 0 }
    let start = 0
    let end = data.length - 1
    if (period.start) {
      const i = data.findIndex((r) => r.date >= period.start!)
      if (i >= 0) start = i
    }
    if (period.end) {
      const i = data.findIndex((r) => r.date > period.end!)
      if (i > 0) end = i - 1
    }
    return start < end ? { start, end } : { start: 0, end: data.length - 1 }
  }, [data, period.start, period.end])

  const from = data[view.start]?.date
  const to = data[view.end]?.date

  /**
   * Refetch metrics and signals for the visible window.
   *
   * Both come from the backend rather than being recomputed in TypeScript: the
   * quant layer is the single source of truth for Sharpe, drawdown and every
   * other figure, and a second implementation here could silently disagree
   * with the one the tests cover.
   */
  const loadWindow = useCallback(
    (startDate?: string, endDate?: string, bars?: number) => {
      if (!startDate || !endDate || !bars) return
      const key = `${asset}|${startDate}|${endDate}`
      const params = adaptiveParams(bars)
      setWindowBusy(true)
      Promise.all([
        api.metrics(asset, { start: startDate, end: endDate }),
        api.backtest(asset, 'sma_crossover', params, DEFAULT_CONFIG, {
          start: startDate,
          end: endDate,
        }),
      ])
        .then(([m, bt]) => {
          // Drop a response for a window the user has already zoomed away from.
          if (wanted.current !== key) return
          setWindowStats({
            summary: m.summary,
            bars: m.bars,
            trades: bt.strategy.trades ?? [],
            params,
          })
        })
        .catch(() => {
          if (wanted.current === key) setWindowStats(null)
        })
        .finally(() => {
          if (wanted.current === key) setWindowBusy(false)
        })
    },
    [asset],
  )

  // Debounced: dragging the chart changes the window continuously, and firing
  // a request per frame would queue dozens of backtests.
  useEffect(() => {
    if (!from || !to) return
    wanted.current = `${asset}|${from}|${to}`
    const bars = view.end - view.start + 1
    const t = setTimeout(() => loadWindow(from, to, bars), 250)
    return () => clearTimeout(t)
  }, [asset, from, to, view.start, view.end, loadWindow])

  if (error) return <ErrorState error={error} onRetry={() => setRows(null)} />
  if (!rows || !data.length) return <Loading what="price history and indicators" />

  const visible = data.slice(view.start, view.end + 1)
  const zoomed = visible.length < data.length

  const indexOfDate = (d: string) => data.findIndex((r) => r.date === d)

  /** Apply the dragged selection, ignoring an accidental click or a sliver. */
  const commitDrag = () => {
    if (dragFrom && dragTo && dragFrom !== dragTo) {
      const a = indexOfDate(dragFrom)
      const b = indexOfDate(dragTo)
      // Works in either drag direction. A selection narrower than the floor is
      // ignored rather than clamped: silently widening what the user dragged
      // would be worse than doing nothing.
      if (a >= 0 && b >= 0 && Math.abs(b - a) + 1 >= MIN_WINDOW_BARS) {
        setPeriod({
          start: data[Math.min(a, b)].date,
          end: data[Math.max(a, b)].date,
        })
      }
    }
    setDragFrom(null)
    setDragTo(null)
  }

  // Markers come from the window's own backtest, so they are real fills for
  // the parameters actually being displayed.
  const trades = windowStats?.trades ?? []
  const entries = new Set(trades.map((t) => t.entry_date))
  const exits = new Set(trades.map((t) => t.exit_date).filter(Boolean) as string[])
  // In-market spans derived from the same trades, so the shading and the
  // markers can never disagree about when a position was held.
  const heldOn = (date: string) =>
    trades.some((t) => date >= t.entry_date && (t.exit_date === null || date < t.exit_date))

  const chartData = visible.map((r) => ({
    ...r,
    buy: entries.has(r.date) ? r.close : null,
    sell: exits.has(r.date) ? r.close : null,
    inMarket: heldOn(r.date) ? 1 : 0,
  }))

  const exposure = chartData.length
    ? chartData.filter((d) => d.inMarket === 1).length / chartData.length
    : 0

  const s = windowStats?.summary
  const shown = windowStats?.params ?? adaptiveParams(visible.length)

  // Headline figures describe the whole series, deliberately: they must not
  // move when you zoom, or the page would have no fixed reference.
  const firstClose = Number(rows[0]?.close ?? 0)
  const growth = firstClose > 0 ? Number(rows[rows.length - 1]?.close) / firstClose : 0
  const years = rows.length / 252

  const tooltipStyle = {
    contentStyle: { background: '#0f172a', border: '1px solid #334155', fontSize: 12 },
  }

  return (
    <>
      <Insight
        label="What this shows"
        tone="neutral"
        headline={
          <>
            {asset} multiplied <Figure value={`${growth.toFixed(1)}×`} /> over{' '}
            {years.toFixed(0)} years. Drag across the chart to set the analysis
            period — every tab recomputes for what you select.
          </>
        }
      >
        Signal periods scale with the window, so there are always buy and sell
        fills to inspect. Headline growth above stays fixed to the full history;
        everything else — here and on every other tab — follows your selection.
      </Insight>

      <Panel
        title={`${asset} — price and trend`}
        subtitle={`${data.length.toLocaleString()} bars available · ${data[0].date} → ${data[lastIndex].date}`}
        wide
      >
        <div className="chart-toolbar">
          <div className="window-stats">
            <span><em>{from}</em> → <em>{to}</em></span>
            <span className="databar-sep">·</span>
            <span>{visible.length.toLocaleString()} bars</span>
            <span className="databar-sep">·</span>
            <span>
              signals SMA {shown.fast}/{shown.slow}
            </span>
            <span className="databar-sep">·</span>
            <span>
              <span className="marker-key buy" />
              {trades.length}
              <span className="marker-key sell" />
              {trades.filter((t) => t.exit_date).length}
            </span>
            <span className="databar-sep">·</span>
            <span>{pct(exposure, 0)} invested</span>
            {windowBusy && <span className="databar-note">updating…</span>}
          </div>
        </div>

        <ResponsiveContainer width="100%" height={400}>
          <ComposedChart
            data={chartData}
            margin={{ top: 8, right: 16, bottom: 0, left: 8 }}
            onMouseDown={(e) => e?.activeLabel && setDragFrom(String(e.activeLabel))}
            onMouseMove={(e) => dragFrom && e?.activeLabel && setDragTo(String(e.activeLabel))}
            onMouseUp={commitDrag}
            onMouseLeave={commitDrag}
            style={{ cursor: dragFrom ? 'ew-resize' : 'crosshair', userSelect: 'none' }}
          >
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} stroke="#64748b" />
            <YAxis
              yAxisId="price"
              scale="log"
              domain={['auto', 'auto']}
              tick={{ fontSize: 11 }}
              stroke="#64748b"
              tickFormatter={(v) => num(v, 0)}
            />
            <YAxis yAxisId="band" orientation="right" domain={[0, 1]} hide />
            <Tooltip {...tooltipStyle} formatter={tipNum} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {/* Full-height shading for the periods a position was held. */}
            <Area
              yAxisId="band"
              dataKey="inMarket"
              name="in market"
              stroke="none"
              fill="#22c55e"
              fillOpacity={0.12}
              isAnimationActive={false}
            />
            <Line yAxisId="price" dataKey="close" name="close" stroke="#e2e8f0" dot={false} strokeWidth={1.4} isAnimationActive={false} />
            <Line yAxisId="price" dataKey="sma50" name="SMA 50" stroke="#4f9cf9" dot={false} strokeWidth={1.1} isAnimationActive={false} />
            <Line yAxisId="price" dataKey="sma200" name="SMA 200" stroke="#f59e0b" dot={false} strokeWidth={1.1} isAnimationActive={false} />
            <Line yAxisId="price" dataKey="ema50" name="EMA 50" stroke="#a78bfa" dot={false} strokeWidth={1} strokeDasharray="3 2" isAnimationActive={false} />
            <Scatter yAxisId="price" dataKey="buy" name="buy" fill="#22c55e" shape="triangle" legendType="triangle" isAnimationActive={false} />
            <Scatter yAxisId="price" dataKey="sell" name="sell" fill="#ef4444" shape="triangle" legendType="triangle" isAnimationActive={false} />
            {/* Live selection rectangle while dragging. */}
            {dragFrom && dragTo && (
              <ReferenceArea
                yAxisId="price"
                x1={dragFrom}
                x2={dragTo}
                fill="#4f9cf9"
                fillOpacity={0.18}
                stroke="#4f9cf9"
                strokeOpacity={0.5}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>

        <Note>
          <strong>Drag across the chart</strong> in either direction to set the
          period — it applies to every tab, not just this chart. Use the Period
          bar at the top to reset or pick a preset. Selections narrower than{' '}
          {MIN_WINDOW_BARS} bars are ignored: below about a trading month the
          signal warm-up leaves no markers and annualised statistics stop
          meaning anything. Signal periods scale to the window — at this width
          the markers come from an SMA {shown.fast}/{shown.slow} crossover. Log
          scale throughout.
        </Note>
      </Panel>

      <Panel
        title="Metrics for the selected period"
        subtitle={
          s
            ? `${from} → ${to} · ${int(windowStats?.bars ?? null)} bars · computed by the backend, not the browser`
            : 'Computing…'
        }
        wide
      >
        {s ? (
          <>
            {(windowStats?.bars ?? 0) < THIN_WINDOW_BARS && (
              <Insight
                label="Read these with caution"
                tone="caution"
                headline={
                  <>
                    Annualised figures from{' '}
                    <Figure value={`${int(windowStats?.bars ?? null)} bars`} /> are
                    statistically thin — Sharpe, CAGR and volatility all scale a
                    handful of daily returns up to a year.
                  </>
                }
              >
                The arithmetic is correct; the inference is not. Return, best day
                and worst day are still exact. Widen the window before drawing
                conclusions from the ratios.
              </Insight>
            )}
            <div className="stats">
              <Stat label="Return" value={pct(s.total_return)} raw={s.total_return} />
              <Stat label="CAGR" value={pct(s.cagr)} raw={s.cagr} />
              <Stat label="Volatility" value={pct(s.volatility)} />
              <Stat label="Sharpe" value={num(s.sharpe)} raw={s.sharpe} />
              <Stat label="Sortino" value={num(s.sortino)} raw={s.sortino} />
              <Stat label="Calmar" value={num(s.calmar)} raw={s.calmar} />
              <Stat label="Max drawdown" value={pct(s.max_drawdown)} raw={s.max_drawdown} higherIsBetter={false} />
              <Stat label="Longest DD" value={`${int(s.max_drawdown_duration)} d`} />
              <Stat label="Best day" value={pct(s.best_day)} raw={s.best_day} />
              <Stat label="Worst day" value={pct(s.worst_day)} raw={s.worst_day} />
              <Stat label="Positive days" value={pct(s.positive_days)} />
            </div>
            <Note>
              Every figure here is recomputed for the visible window by the same
              code the test suite covers — the browser never does quant maths of
              its own, so these cannot drift from the Risk and Backtest tabs.
            </Note>
          </>
        ) : (
          <Loading what="metrics for this window" />
        )}
      </Panel>

      <Panel title="Volume" subtitle={zoomed ? 'Following the selection' : undefined}>
        <ResponsiveContainer width="100%" height={160}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} stroke="#64748b" />
            <YAxis tick={{ fontSize: 11 }} stroke="#64748b" tickFormatter={(v) => tipVolume(v)} />
            <Tooltip {...tooltipStyle} formatter={tipVolume} />
            <Bar dataKey="volume" fill="#334155" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Panel>

      <Panel
        title="Fills in this period"
        subtitle={`SMA ${shown.fast}/${shown.slow} · ${trades.length} trade${trades.length === 1 ? '' : 's'}`}
      >
        {trades.length ? (
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Entry</th><th>Exit</th><th>In</th><th>Out</th>
                  <th>Net</th><th>Return</th><th>Bars</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i} className={t.is_open ? 'open-trade' : ''}>
                    <td>{t.entry_date}</td>
                    <td>{t.exit_date ?? 'open'}</td>
                    <td>{num(t.entry_price)}</td>
                    <td>{num(t.exit_price)}</td>
                    <td className={(t.net_pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{money(t.net_pnl)}</td>
                    <td className={(t.return_pct ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(t.return_pct)}</td>
                    <td>{t.bars_held}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Note>
            No completed crossover in this window — the signal never flipped.
            Zoom out, or pick a period containing a trend change.
          </Note>
        )}
      </Panel>
    </>
  )
}
