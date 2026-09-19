import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, DEFAULT_CONFIG, type Bar as OhlcBar, type Trade } from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { Figure, Insight } from '../components/Insight'
import { money, num, pct, tipNum, tipVolume } from '../format'

/** Zoom presets, in trading days. `null` means the whole series. */
const ZOOMS: { label: string; bars: number | null }[] = [
  { label: 'All', bars: null },
  { label: '5Y', bars: 252 * 5 },
  { label: '3Y', bars: 252 * 3 },
  { label: '1Y', bars: 252 },
  { label: '6M', bars: 126 },
  { label: '3M', bars: 63 },
]

/** Price, moving averages, volume and buy/sell markers for one asset. */
export function Overview({ asset }: { asset: string }) {
  const [rows, setRows] = useState<OhlcBar[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [signals, setSignals] = useState<{ date: string; position: number }[]>([])
  const [trades, setTrades] = useState<Trade[]>([])

  // Visible index window, driven by the brush and the zoom presets. Kept as
  // indices rather than dates because that is what Recharts' Brush speaks.
  const [range, setRange] = useState<{ start: number; end: number } | null>(null)

  const load = () => {
    setRows(null)
    setError(null)
    setRange(null)
    Promise.all([
      // EMA 50 alongside SMA 50/200 — the brief asks for both on the chart.
      api.indicators(asset, 50, 200, 20, 50),
      // Shared defaults rather than a literal, so the shading here always
      // reflects the same execution assumptions as the Backtest tab.
      api.backtest(asset, 'sma_crossover', {}, DEFAULT_CONFIG),
    ])
      .then(([ind, bt]) => {
        setRows(ind.rows)
        setSignals(
          bt.strategy.curves.dates.map((date, i) => ({
            date,
            position: bt.strategy.curves.position[i],
          })),
        )
        setTrades(bt.strategy.trades ?? [])
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [asset])

  // Only plot from where the 200-day average exists; before that the chart
  // would show a line appearing out of nowhere.
  const data = useMemo(() => {
    if (!rows) return []
    const positions = new Map(signals.map((s) => [s.date, s.position]))
    const entries = new Set(trades.map((t) => t.entry_date))
    const exits = new Set(trades.map((t) => t.exit_date).filter(Boolean) as string[])
    return rows
      .filter((r) => r.sma_200 !== null)
      .map((r) => ({
        date: String(r.date),
        close: r.close,
        sma50: r.sma_50,
        sma200: r.sma_200,
        ema50: r.ema_50,
        volume: r.volume,
        // Discrete fills from the trade log, so the markers are the actual
        // executions rather than a re-derived guess at them.
        buy: entries.has(String(r.date)) ? r.close : null,
        sell: exits.has(String(r.date)) ? r.close : null,
        // 1 when the crossover strategy holds a position. Plotted against a
        // hidden 0-1 axis so it renders as a full-height background band rather
        // than an area under the price line.
        inMarket: positions.get(String(r.date)) === 1 ? 1 : 0,
      }))
  }, [rows, signals, trades])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!rows || !data.length) return <Loading what="price history and indicators" />

  const lastIndex = data.length - 1
  const view = range ?? { start: 0, end: lastIndex }
  const visible = data.slice(view.start, view.end + 1)

  const zoomTo = (bars: number | null) => {
    if (bars === null || bars >= data.length) return setRange(null)
    setRange({ start: Math.max(0, data.length - bars), end: lastIndex })
  }

  const activeZoom = (bars: number | null) => {
    const span = view.end - view.start + 1
    if (bars === null) return span === data.length
    return span === bars && view.end === lastIndex
  }

  // --- figures for the visible window, not the whole series ---------------
  const vFirst = visible[0]
  const vLast = visible[visible.length - 1]
  const vChange =
    Number(vFirst?.close) > 0 ? Number(vLast?.close) / Number(vFirst?.close) - 1 : 0
  const vBuys = visible.filter((d) => d.buy !== null).length
  const vSells = visible.filter((d) => d.sell !== null).length
  const vExposure = visible.length
    ? visible.filter((d) => d.inMarket === 1).length / visible.length
    : 0
  const zoomed = visible.length < data.length

  // --- figures for the whole series (the headline) ------------------------
  const last = rows[rows.length - 1]
  const firstClose = Number(rows[0]?.close ?? 0)
  const growth = firstClose > 0 ? Number(last?.close) / firstClose : 0
  const inMarketShare = data.filter((d) => d.inMarket === 1).length / data.length
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
            {years.toFixed(0)} years, while a 50/200 crossover would have been
            invested only <Figure value={pct(inMarketShare, 0)} /> of the charted
            period.
          </>
        }
      >
        The green bands are the invested periods. Time out of the market is the
        price a trend filter charges for avoiding the crashes — the Backtest tab
        settles whether that trade was worth making.
      </Insight>

      <Panel
        title={`${asset} — price and trend`}
        subtitle={`${data.length.toLocaleString()} bars · ${data[0].date} → ${data[lastIndex].date}`}
        wide
      >
        <div className="chart-toolbar">
          <div className="presets">
            <span className="presets-label">Zoom</span>
            {ZOOMS.map((z) => (
              <button
                key={z.label}
                className={`chip${activeZoom(z.bars) ? ' active' : ''}`}
                onClick={() => zoomTo(z.bars)}
                disabled={z.bars !== null && z.bars >= data.length}
              >
                {z.label}
              </button>
            ))}
          </div>

          {/* Stats recomputed for whatever is on screen, so zooming in answers
              "what happened here?" rather than just magnifying the picture. */}
          <div className="window-stats">
            <span>
              <em>{vFirst?.date}</em> → <em>{vLast?.date}</em>
            </span>
            <span className="databar-sep">·</span>
            <span>{visible.length.toLocaleString()} bars</span>
            <span className="databar-sep">·</span>
            <span className={vChange >= 0 ? 'pos' : 'neg'}>{pct(vChange)}</span>
            <span className="databar-sep">·</span>
            <span>
              <span className="marker-key buy" /> {vBuys}
              <span className="marker-key sell" /> {vSells}
            </span>
            <span className="databar-sep">·</span>
            <span>{pct(vExposure, 0)} invested</span>
          </div>
        </div>

        <ResponsiveContainer width="100%" height={400}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
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
            {/* Full-height band marking the periods the strategy was invested. */}
            <Area
              yAxisId="band"
              dataKey="inMarket"
              name="in market (SMA 50/200)"
              stroke="none"
              fill="#22c55e"
              fillOpacity={0.13}
              isAnimationActive={false}
            />
            <Line yAxisId="price" dataKey="close" name="close" stroke="#e2e8f0" dot={false} strokeWidth={1.4} />
            <Line yAxisId="price" dataKey="sma50" name="SMA 50" stroke="#4f9cf9" dot={false} strokeWidth={1.2} />
            <Line yAxisId="price" dataKey="sma200" name="SMA 200" stroke="#f59e0b" dot={false} strokeWidth={1.2} />
            <Line yAxisId="price" dataKey="ema50" name="EMA 50" stroke="#a78bfa" dot={false} strokeWidth={1.1} strokeDasharray="3 2" />
            {/* Actual fills from the trade log. Marker size grows as you zoom
                in, because at full extent 2,300 bars make them unreadable. */}
            <Scatter
              yAxisId="price"
              dataKey="buy"
              name="buy"
              fill="#22c55e"
              shape="triangle"
              legendType="triangle"
              isAnimationActive={false}
            />
            <Scatter
              yAxisId="price"
              dataKey="sell"
              name="sell"
              fill="#ef4444"
              shape="triangle"
              legendType="triangle"
              isAnimationActive={false}
            />
            <Brush
              dataKey="date"
              height={30}
              travellerWidth={9}
              stroke="#4f9cf9"
              fill="#0f172a"
              startIndex={view.start}
              endIndex={view.end}
              onChange={(r) => {
                const { startIndex, endIndex } = r as { startIndex?: number; endIndex?: number }
                if (startIndex === undefined || endIndex === undefined) return
                setRange(
                  startIndex === 0 && endIndex === lastIndex
                    ? null
                    : { start: startIndex, end: endIndex },
                )
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>

        <Note>
          {zoomed ? (
            <>
              Showing <strong>{visible.length.toLocaleString()}</strong> of{' '}
              {data.length.toLocaleString()} bars. Drag the handles under the
              chart to adjust, or press <strong>All</strong> to zoom back out —
              every figure in the bar above follows the visible window.
            </>
          ) : (
            <>
              Drag the handles under the chart, or use the zoom buttons, to
              inspect a period closely — the buy and sell triangles are hard to
              read across a full decade. Log scale, because a linear axis
              compresses the early years into a flat line.
            </>
          )}
        </Note>
      </Panel>

      <Panel title="Volume" subtitle={zoomed ? 'Following the zoom above' : undefined} wide>
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={visible} margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} stroke="#64748b" />
            <YAxis tick={{ fontSize: 11 }} stroke="#64748b" tickFormatter={(v) => tipVolume(v)} />
            <Tooltip {...tooltipStyle} formatter={tipVolume} />
            <Bar dataKey="volume" fill="#334155" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Panel>

      {zoomed && vBuys + vSells > 0 && (
        <Panel
          title="Fills in view"
          subtitle={`${vBuys} buy${vBuys === 1 ? '' : 's'}, ${vSells} sell${vSells === 1 ? '' : 's'}`}
          wide
        >
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Entry</th><th>Exit</th><th>In</th><th>Out</th>
                  <th>Net P&amp;L</th><th>Return</th><th>Bars</th>
                </tr>
              </thead>
              <tbody>
                {trades
                  .filter(
                    (t) =>
                      (t.entry_date >= (vFirst?.date ?? '') && t.entry_date <= (vLast?.date ?? '')) ||
                      (t.exit_date != null &&
                        t.exit_date >= (vFirst?.date ?? '') &&
                        t.exit_date <= (vLast?.date ?? '')),
                  )
                  .map((t, i) => (
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
          <Note>
            Only the trades that opened or closed inside the visible window. Zoom
            out to see the rest, or use the Backtest tab for the full log.
          </Note>
        </Panel>
      )}
    </>
  )
}
