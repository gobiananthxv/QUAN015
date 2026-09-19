import { useEffect, useState } from 'react'
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, type Bar as OhlcBar } from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { num, tipNum, tipVolume } from '../format'

/** Price, moving averages, volume and buy/sell markers for one asset. */
export function Overview({ asset }: { asset: string }) {
  const [rows, setRows] = useState<OhlcBar[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [signals, setSignals] = useState<{ date: string; position: number }[]>([])

  const load = () => {
    setRows(null)
    setError(null)
    Promise.all([
      api.indicators(asset, 50, 200),
      api.backtest(asset, 'sma_crossover', {}, {
        initial_capital: 100000, commission_bps: 10, slippage_bps: 5,
        position_pct: 1, allow_short: false,
      }),
    ])
      .then(([ind, bt]) => {
        setRows(ind.rows)
        setSignals(
          bt.strategy.curves.dates.map((date, i) => ({
            date,
            position: bt.strategy.curves.position[i],
          })),
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
      volume: r.volume,
      // 1 when the crossover strategy holds a position. Plotted against a
      // hidden 0-1 axis so it renders as a full-height background band rather
      // than an area under the price line.
      inMarket: positions.get(r.date) === 1 ? 1 : 0,
    }))

  const last = rows[rows.length - 1]
  const first = data[0]

  return (
    <>
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
          </ComposedChart>
        </ResponsiveContainer>
        <Note>
          Log scale — over a decade a linear axis compresses the early years into
          a flat line. The green band marks the periods a 50/200 SMA crossover
          would have been invested.
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
