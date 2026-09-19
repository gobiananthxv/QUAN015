import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, type Summary } from '../api'
import { ErrorState, Loading, Note, Panel, Stat } from '../components/Common'
import { int, num, pct, tipPct } from '../format'

type Point = { date: string; value: number | null }

export function Risk({ asset }: { asset: string }) {
  const [data, setData] = useState<{
    summary: Summary
    annFactor: number
    cumulative: Point[]
    drawdown: Point[]
    vol: Point[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setData(null)
    setError(null)
    api
      .metrics(asset)
      .then((m) =>
        setData({
          summary: m.summary,
          annFactor: m.ann_factor,
          cumulative: m.cumulative.map((p) => ({ date: p.date, value: p.cum })),
          drawdown: m.drawdown.map((p) => ({ date: p.date, value: p.dd })),
          vol: m.rolling_vol.map((p) => ({ date: p.date, value: p.vol })),
        }),
      )
      .catch((e) => setError(e.message))
  }

  useEffect(load, [asset])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!data) return <Loading what="risk metrics" />

  const s = data.summary
  const axis = { tick: { fontSize: 11 }, stroke: '#64748b' }
  const tooltip = {
    contentStyle: { background: '#0f172a', border: '1px solid #334155', fontSize: 12 },
  }

  return (
    <>
      <Panel
        title={`${asset} — buy and hold`}
        subtitle={`Annualised using ${data.annFactor} periods per year`}
        wide
      >
        <div className="stats">
          <Stat label="Total return" value={pct(s.total_return)} raw={s.total_return} />
          <Stat label="CAGR" value={pct(s.cagr)} raw={s.cagr} />
          <Stat label="Volatility" value={pct(s.volatility)} hint="Annualised standard deviation of daily returns" />
          <Stat label="Sharpe" value={num(s.sharpe)} raw={s.sharpe} />
          <Stat label="Sortino" value={num(s.sortino)} raw={s.sortino} hint="Penalises downside deviation only" />
          <Stat label="Calmar" value={num(s.calmar)} raw={s.calmar} hint="CAGR divided by max drawdown" />
          <Stat label="Max drawdown" value={pct(s.max_drawdown)} raw={s.max_drawdown} higherIsBetter={false} />
          <Stat label="Longest drawdown" value={`${int(s.max_drawdown_duration)} d`} hint="Consecutive bars below a prior peak" />
          <Stat label="Positive days" value={pct(s.positive_days)} />
        </div>
        <Note>
          The annualisation factor is a property of the asset, not a constant.
          Crypto trades 365 days a year; equities and futures roughly 252.
        </Note>
      </Panel>

      <Panel title="Cumulative return" wide>
        <ResponsiveContainer width="100%" height={230}>
          <LineChart data={data.cumulative} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} {...axis} />
            <YAxis tickFormatter={(v) => pct(v, 0)} {...axis} />
            <Tooltip {...tooltip} formatter={tipPct} />
            <Line dataKey="value" stroke="#22c55e" dot={false} strokeWidth={1.4} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Drawdown" subtitle="Distance below the running peak">
        <ResponsiveContainer width="100%" height={210}>
          <AreaChart data={data.drawdown} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} {...axis} />
            <YAxis tickFormatter={(v) => pct(v, 0)} {...axis} />
            <Tooltip {...tooltip} formatter={tipPct} />
            <Area dataKey="value" stroke="#ef4444" fill="#ef4444" fillOpacity={0.22} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
        <Note>Every point is the loss from the highest value reached so far.</Note>
      </Panel>

      <Panel title="Rolling 30-day volatility" subtitle="Annualised">
        <ResponsiveContainer width="100%" height={210}>
          <LineChart data={data.vol} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} {...axis} />
            <YAxis tickFormatter={(v) => pct(v, 0)} {...axis} />
            <Tooltip {...tooltip} formatter={tipPct} />
            <Line dataKey="value" stroke="#a78bfa" dot={false} strokeWidth={1.3} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <Note>Volatility clusters — calm and turbulent periods each persist.</Note>
      </Panel>
    </>
  )
}
