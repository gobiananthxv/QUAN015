import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, type Summary } from '../api'
import { describePeriod, usePeriod } from '../period'
import { ErrorState, Loading, Note, Panel, Stat } from '../components/Common'
import { Figure, Insight } from '../components/Insight'
import { int, num, pct, tipPct } from '../format'

type Point = { date: string; value: number | null }

export function Risk({ asset }: { asset: string }) {
  const { period, bounds } = usePeriod()
  const [data, setData] = useState<{
    summary: Summary
    annFactor: number
    cumulative: Point[]
    drawdown: Point[]
    vol: Point[]
    rolling: Point[]
    returnWindow: number
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setData(null)
    setError(null)
    api
      .metrics(asset, period)
      .then((m) =>
        setData({
          summary: m.summary,
          annFactor: m.ann_factor,
          cumulative: m.cumulative.map((p) => ({ date: p.date, value: p.cum })),
          drawdown: m.drawdown.map((p) => ({ date: p.date, value: p.dd })),
          vol: m.rolling_vol.map((p) => ({ date: p.date, value: p.vol })),
          rolling: m.rolling_returns.map((p) => ({ date: p.date, value: p.ret })),
          returnWindow: m.return_window,
        }),
      )
      .catch((e) => setError(e.message))
  }

  useEffect(load, [asset, period])

  if (error) return <ErrorState error={error} onRetry={load} />
  if (!data) return <Loading what="risk metrics" />

  const s = data.summary
  // "How far did it fall, and how long were you underwater?" is the question a
  // return figure never answers.
  const dd = s.max_drawdown ?? 0
  const recovery = (1 / (1 + dd) - 1)
  const ddDays = s.max_drawdown_duration ?? 0
  const axis = { tick: { fontSize: 11 }, stroke: '#64748b' }
  const tooltip = {
    contentStyle: { background: '#0f172a', border: '1px solid #334155', fontSize: 12 },
  }

  return (
    <>
      <Insight
        label="The number behind the return"
        tone={dd < -0.5 ? 'bad' : dd < -0.3 ? 'caution' : 'neutral'}
        headline={
          <>
            Holding {asset} meant surviving a <Figure value={pct(dd)} tone="bad" />{' '}
            drawdown lasting <Figure value={`${int(ddDays)} days`} />, and needing
            a <Figure value={pct(recovery)} /> gain just to get back to even.
          </>
        }
      >
        Compounding is not symmetric: a 50% loss requires a 100% gain to recover.
        A CAGR of {pct(s.cagr)} is only achievable by someone who did not sell
        during that stretch.
      </Insight>

      <Panel
        title={`${asset} — buy and hold`}
        subtitle={`${describePeriod(period, bounds)} · annualised using ${data.annFactor} periods per year`}
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

      <Panel
        title={`Rolling ${Math.round(data.returnWindow / 252)}-year return`}
        subtitle="What you would have made buying on each date and holding"
        wide
      >
        <ResponsiveContainer width="100%" height={230}>
          <AreaChart data={data.rolling} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} {...axis} />
            <YAxis tickFormatter={(v) => pct(v, 0)} {...axis} />
            <Tooltip {...tooltip} formatter={tipPct} />
            <ReferenceLine y={0} stroke="#64748b" />
            <Area dataKey="value" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.16} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
        <Note>
          Each point is the return from buying on that date and holding for a
          year. Where the line dips below zero, a buyer waited more than a year
          to break even.
        </Note>
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
