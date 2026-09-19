import { useEffect, useState } from 'react'
import {
  Area,
  Bar,
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
import { api, DEFAULT_CONFIG, type Bar as OhlcBar } from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { Figure, Insight } from '../components/Insight'
import { num, pct, tipNum, tipVolume } from '../format'

/** Price, moving averages, volume and buy/sell markers for one asset. */
export function Overview({ asset }: { asset: string }) {
  const [rows, setRows] = useState<OhlcBar[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [signals, setSignals] = useState<{ date: string; position: number }[]>([])
  const [entries, setEntries] = useState<Set<string>>(new Set())
  const [exits, setExits] = useState<Set<string>>(new Set())

  const load = () => {
    setRows(null)
    setError(null)
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
        // Discrete entry/exit dates straight from the trade log, so the markers
        // are the actual fills rather than a re-derived guess at them.
        setEntries(new Set((bt.strategy.trades ?? []).map((t) => t.entry_date)))
        setExits(
          new Set(
            (bt.strategy.trades ?? [])
              .map((t) => t.exit_date)
              .filter((d): d is string => Boolean(d)),
          ),
        )
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [asset])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!rows) return <Loading what="price history and indicators" />

  // Only plot from where the 200-day average exists; before that the chart
  // would show a line appearing out of nowhere.
  const positions = new Map(signals.map((s) => [s.date, s.position]))
  const data = rows
    .filter((r) => r.sma_200 !== null)
    .map((r) => ({
      date: r.date,
      close: r.close,
      sma50: r.sma_50,
      sma200: r.sma_200,
      ema50: r.ema_50,
      volume: r.volume,
      buy: entries.has(String(r.date)) ? r.close : null,
      sell: exits.has(String(r.date)) ? r.close : null,
      // 1 when the crossover strategy holds a position. Plotted against a
      // hidden 0-1 axis so it renders as a full-height background band rather
      // than an area under the price line.
      inMarket: positions.get(r.date) === 1 ? 1 : 0,
    }))

  const last = rows[rows.length - 1]
  const first = data[0]

  // Computed, so it stays true when the asset changes or the data is refreshed.
  //
  // Growth is measured over the FULL series, not the charted window. The chart
  // starts where the 200-day average becomes defined, which is ~200 bars in —
  // measuring from there would report 63x for NVDA while the Risk tab reports
  // 142x for the same asset, and the two would read as a contradiction.
  const firstClose = Number(rows[0]?.close ?? 0)
  const lastClose = Number(last?.close ?? 0)
  const growth = firstClose > 0 ? lastClose / firstClose : 0
  const inMarketShare = data.length
    ? data.filter((d) => d.inMarket === 1).length / data.length
    : 0
  const years = rows.length / 252

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
        subtitle={`${data.length.toLocaleString()} bars · ${first?.date} → ${last.date}`}
        wide
      >
        <ResponsiveContainer width="100%" height={380}>
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
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
              formatter={tipNum}
            />
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
            {/* Actual fills from the trade log. */}
            <Scatter yAxisId="price" dataKey="buy" name="buy" fill="#22c55e" shape="triangle" isAnimationActive={false} />
            <Scatter yAxisId="price" dataKey="sell" name="sell" fill="#ef4444" shape="triangle" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
        <Note>
          Log scale — over a decade a linear axis compresses the early years into
          a flat line. Green bands mark the periods a 50/200 SMA crossover would
          have been invested; the green and red triangles are its actual buy and
          sell fills, taken from the trade log rather than re-derived.
        </Note>
      </Panel>

      <Panel title="Volume" wide>
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} stroke="#64748b" />
            <YAxis tick={{ fontSize: 11 }} stroke="#64748b" tickFormatter={(v) => tipVolume(v)} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
              formatter={tipVolume}
            />
            <Bar dataKey="volume" fill="#334155" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Panel>
    </>
  )
}
