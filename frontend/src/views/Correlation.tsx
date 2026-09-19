import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, type Num } from '../api'
import { describePeriod, usePeriod } from '../period'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { Figure, Insight } from '../components/Insight'
import { num, tipNum3 } from '../format'

const PAIR_COLORS = ['#4f9cf9', '#f59e0b', '#22c55e', '#a78bfa', '#ef4444', '#14b8a6']

/** Blue for negative, red for positive — diverging around zero. */
function heatColor(v: Num): string {
  if (v === null) return '#1e293b'
  const t = Math.min(Math.abs(v), 1)
  return v >= 0 ? `rgba(239, 68, 68, ${0.12 + t * 0.75})` : `rgba(79, 156, 249, ${0.12 + t * 0.75})`
}

export function Correlation() {
  const { period, bounds } = usePeriod()
  const [data, setData] = useState<Awaited<ReturnType<typeof api.correlation>> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [window, setWindow] = useState(90)

  const load = () => {
    setData(null)
    setError(null)
    api.correlation(window, period).then(setData).catch((e) => setError(e.message))
  }

  useEffect(load, [window, period])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!data) return <Loading what="correlations" />

  const lookup = new Map(data.matrix.map((c) => [`${c.a}|${c.b}`, c.value]))
  const pairs = Object.keys(data.rolling[0] ?? {}).filter((k) => k !== 'date')

  // Find the pair whose relationship moved most — that is the headline.
  let widest = { pair: '', min: 0, max: 0, swing: -1, staticCorr: 0 }
  for (const pair of pairs) {
    const values = data.rolling
      .map((r) => r[pair])
      .filter((v): v is number => typeof v === 'number')
    if (!values.length) continue
    const min = Math.min(...values)
    const max = Math.max(...values)
    if (max - min > widest.swing) {
      const [a, b] = pair.split('~')
      widest = {
        pair: pair.replace('~', ' / '),
        min,
        max,
        swing: max - min,
        staticCorr: Number(lookup.get(`${a}|${b}`) ?? 0),
      }
    }
  }

  return (
    <>
      <Insight
        label="Why one correlation number is not enough"
        tone="caution"
        headline={
          <>
            {widest.pair} look almost unrelated overall at{' '}
            <Figure value={num(widest.staticCorr, 2)} /> — yet their 90-day
            correlation ranged from <Figure value={num(widest.min, 2)} tone="good" />{' '}
            to <Figure value={num(widest.max, 2)} tone="bad" /> across the period.
          </>
        }
      >
        The full-sample figure averages those two opposite regimes into something
        that never actually happened. Diversification measured once is not
        diversification you can rely on.
      </Insight>

      <Panel
        title="Correlation matrix"
        subtitle={`${describePeriod(period, bounds)} · ${data.observations.toLocaleString()} common trading days`}
      >
        <table className="heatmap">
          <thead>
            <tr>
              <th />
              {data.assets.map((a) => (
                <th key={a}>{a}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.assets.map((a) => (
              <tr key={a}>
                <th>{a}</th>
                {data.assets.map((b) => {
                  const v = lookup.get(`${a}|${b}`) ?? null
                  return (
                    <td key={b} style={{ background: heatColor(v) }}>
                      {num(v, 3)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <Note>
          Computed on <strong>returns</strong>, not price levels — two unrelated
          assets that both trend upward correlate near 1 in levels. Assets are
          aligned to a common trading calendar, so weekends (when only crypto
          trades) cannot drag the figure toward zero.
        </Note>
      </Panel>

      <Panel title="Rolling correlation" subtitle="Relationships are not constant" wide>
        <div className="controls inline">
          <label>
            Window
            <select value={window} onChange={(e) => setWindow(Number(e.target.value))}>
              {[30, 60, 90, 180, 365].map((w) => (
                <option key={w} value={w}>
                  {w} days
                </option>
              ))}
            </select>
          </label>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data.rolling} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} stroke="#64748b" />
            <YAxis domain={[-1, 1]} tick={{ fontSize: 11 }} stroke="#64748b" />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
              formatter={tipNum3}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine y={0} stroke="#475569" />
            {pairs.map((p, i) => (
              <Line
                key={p}
                dataKey={p}
                name={p.replace('~', ' / ')}
                stroke={PAIR_COLORS[i % PAIR_COLORS.length]}
                dot={false}
                strokeWidth={1.3}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <Note>
          The single figure in the matrix above hides this. Pairs swing between
          strongly positive and outright negative — diversification that holds in
          calm markets can disappear exactly when it is needed.
        </Note>
      </Panel>
    </>
  )
}
