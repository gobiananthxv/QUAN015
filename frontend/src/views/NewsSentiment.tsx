import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  api,
  type NewsAnalysis,
  type NewsChartData,
  type DirectDependency,
  type NumericPrediction,
} from '../api'
import { ErrorState, Loading, Note, Panel } from '../components/Common'
import { Figure, Insight, type Tone } from '../components/Insight'
import type { ChartDescriptor } from '../page/pageContext'
import { useRegisterCharts } from '../page/pageContext'
import { ASSET_COLORS, money, num, pct, tipMoney } from '../format'

const PLATFORM_KEYS = ['GOLD', 'BTC', 'NVDA']

type Mode = 'text' | 'image'

function sentimentTone(s: string | null | undefined): Tone | undefined {
  if (!s) return undefined
  return s.toLowerCase() === 'bullish' ? 'good' : s.toLowerCase() === 'bearish' ? 'bad' : undefined
}

function impactTone(i: string | null | undefined): Tone | undefined {
  if (!i) return undefined
  return i.toLowerCase() === 'bullish' ? 'good' : i.toLowerCase() === 'bearish' ? 'bad' : undefined
}

const KEY: Record<string, string> = {
  GOLD: 'Gold',
  BTC: 'Bitcoin',
  NVDA: 'NVIDIA',
}
const nameOf = (k: string) => KEY[k.toUpperCase()] ?? k

function ProbBar({ value }: { value: number | null }) {
  const v = value === null || !Number.isFinite(value) ? 0 : Math.max(0, Math.min(1, value))
  return (
    <div className="prob-bar" title={`${pct(v, 0)}`}>
      <span className="prob-bar-fill" style={{ width: `${v * 100}%` }} />
    </div>
  )
}

function MiniChart({ data }: { data: NewsChartData }) {
  const rows = data.dates.map((d, i) => ({
    date: d,
    price: data.prices[i],
  }))
  const color = ASSET_COLORS[data.asset] ?? '#4f9cf9'
  return (
    <div className="mini-chart">
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#1e293b" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} minTickGap={40} hide />
          <YAxis
            domain={['auto', 'auto']}
            tick={{ fontSize: 10, fill: '#64748b' }}
            width={46}
            tickFormatter={(v) => money(v)}
          />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
            formatter={tipMoney}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Line
            dataKey="price"
            name="Price"
            stroke={color}
            strokeWidth={1.8}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function Chain({ chain }: { chain: string[] }) {
  return (
    <div className="chain">
      {chain.map((step, i) => (
        <span key={i} className="chain-step">
          {step}
          {i < chain.length - 1 && <span className="chain-arrow">→</span>}
        </span>
      ))}
    </div>
  )
}

function DirectCard({ dep, charts }: { dep: DirectDependency; charts: Record<string, NewsChartData> }) {
  const tone = impactTone(dep.impact)
  const chart = charts[dep.asset.toUpperCase()]
  return (
    <div className="dep-card">
      <div className="dep-card-head">
        <span className={`badge ${tone ?? 'warn'}`}>{dep.impact}</span>
        <strong>{nameOf(dep.asset)}</strong>
        <span className="dep-change">{dep.expected_change ?? '—'}</span>
      </div>
      <div className="dep-meta">
        <span>
          Correlation <em>{num(dep.correlation_strength)}</em>
        </span>
        <span>
          Confidence <em>{pct(dep.confidence, 0)}</em>
        </span>
      </div>
      <ProbBar value={dep.confidence} />
      {chart ? <MiniChart data={chart} /> : <Note>Chart unavailable for {nameOf(dep.asset)}.</Note>}
    </div>
  )
}

function PredictionRow({ p }: { p: NumericPrediction }) {
  return (
    <tr>
      <td>{p.mention ?? '—'}</td>
      <td>{p.asset_impact ? nameOf(p.asset_impact) : '—'}</td>
      <td>{p.predicted_move ?? '—'}</td>
      <td>{p.timeframe ?? '—'}</td>
      <td>
        <div className="prob-cell">
          <ProbBar value={p.probability} />
          <span>{pct(p.probability, 0)}</span>
        </div>
      </td>
    </tr>
  )
}

/**
 * News Sentiment — live financial news analysis.
 *
 * Pasta a news article or upload a screenshot; Gemini returns a six-part
 * report (article overview, entities, direct/indirect dependencies, numeric
 * predictions, portfolio correlation). The dependency charts are NOT model
 * output: they read the same committed price snapshot as every other view.
 */
export function NewsSentiment() {
  const [mode, setMode] = useState<Mode>('text')
  const [provider, setProvider] = useState<'google' | 'feather'>('google')
  const [text, setText] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [analysis, setAnalysis] = useState<NewsAnalysis | null>(null)
  const [charts, setCharts] = useState<Record<string, NewsChartData>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const assetKeys = useMemo(() => {
    if (!analysis) return []
    const direct = analysis.direct_dependencies?.assets_affected?.map((d) => d.asset) ?? []
    const indirect =
      analysis.indirect_dependencies?.relationships?.flatMap((r) => r.affected_assets) ?? []
    return [...new Set([...direct, ...indirect])].filter((a) =>
      PLATFORM_KEYS.includes(a.toUpperCase()),
    )
  }, [analysis])

  useEffect(() => {
    if (!assetKeys.length) return
    let cancelled = false
    Promise.all(
      assetKeys.map(async (k) => {
        try {
          const data = await api.newsChartData(k, 5, 0)
          return { key: k.toUpperCase(), data }
        } catch {
          return null
        }
      }),
    ).then((results) => {
      if (cancelled) return
      const next: Record<string, NewsChartData> = {}
      for (const r of results) if (r) next[r.key] = r.data
      setCharts(next)
    })
    return () => {
      cancelled = true
    }
  }, [assetKeys])

  const run = async () => {
    if (mode === 'text' && !text.trim()) {
      setError('Paste a news article first.')
      return
    }
    if (mode === 'image' && !image) {
      setError('Choose an image first.')
      return
    }
    setBusy(true)
    setError(null)
    setAnalysis(null)
    setCharts({})
    try {
      const result = mode === 'text' 
        ? await api.analyzeText(text, provider) 
        : await api.analyzeImage(image!, provider)
      setAnalysis(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  useRegisterCharts(
    useMemo<ChartDescriptor[]>(() => {
      if (!analysis) return []
      const meta = analysis.article_metadata
      const direct = analysis.direct_dependencies?.assets_affected ?? []
      const indirect = analysis.indirect_dependencies?.relationships ?? []
      const corr = analysis.correlation_analysis
      return [
        {
          id: 'news_sentiment_analysis',
          title: 'News Sentiment Analysis',
          chart_type: 'news',
          formula:
            'The article/screenshot is mapped onto platform assets with sentiment, direct and indirect dependency chains, numeric predictions and portfolio correlation',
          data_source: 'Live Gemini/Feather call; dependency charts read the committed price snapshot',
          result: {
            provider,
            mode,
            headline: meta?.headline ?? null,
            sentiment: meta?.sentiment ?? null,
            color_psychology: meta?.color_psychology ?? null,
            urgency_level: meta?.urgency_level ?? null,
            publication_date: meta?.publication_date ?? null,
            summary: meta?.summary ?? null,
            direct_dependencies: direct.map((d) => ({
              asset: d.asset,
              impact: d.impact,
              expected_change: d.expected_change ?? null,
              correlation_strength: d.correlation_strength,
              confidence: d.confidence,
              lookback_days: d.chart_data_needed?.lookback_days ?? null,
            })),
            indirect_relationships: indirect.map((r) => ({
              chain: r.chain,
              expected_timeline_days: r.expected_timeline_days,
              confidence: r.confidence,
              affected_assets: r.affected_assets,
            })),
            numeric_predictions: (analysis.numeric_predictions?.predictions ?? []).map((p) => ({
              mention: p.mention ?? null,
              asset_impact: p.asset_impact ?? null,
              predicted_move: p.predicted_move ?? null,
              timeframe: p.timeframe ?? null,
              probability: p.probability,
            })),
            correlation_shift: corr?.portfolio_correlation_shift ?? null,
            contagion_risk: corr?.cross_asset_contagion_risk ?? null,
            diversification_impact: corr?.diversification_impact ?? null,
            contagion_summary: corr?.summary ?? null,
          },
        },
      ]
    }, [analysis, provider, mode]),
  )

  if (error) return <ErrorState error={error} onRetry={run} />
  if (busy) return <Loading what="the news analysis" />

  const meta = analysis?.article_metadata
  const entities = analysis?.extracted_entities
  const direct = analysis?.direct_dependencies?.assets_affected ?? []
  const indirect = analysis?.indirect_dependencies?.relationships ?? []
  const predictions = analysis?.numeric_predictions?.predictions ?? []
  const corr = analysis?.correlation_analysis
  const tone: Tone = sentimentTone(meta?.sentiment) ?? 'neutral'

  return (
    <>
      <Insight
        label="News sentiment"
        tone={tone}
        headline={
          analysis ? (
            <>
              Article reads <Figure value={(meta?.sentiment ?? 'neutral').toUpperCase()} tone={tone} />
              {' — '}
              {meta?.headline ?? 'an analysis of this article'}
              {direct.length > 0 && (
                <>
                  {' · the most direct move is '}
                  <Figure value={nameOf(direct[0].asset)} />{' '}
                  <Figure value={direct[0].expected_change ?? '—'} tone={impactTone(direct[0].impact)} />
                </>
              )}
            </>
          ) : (
            <>Paste a news article or a screenshot and let Gemini map it onto the platform.</>
          )
        }
      >
        {analysis && corr?.summary ? (
          <>
            <strong>Portfolio read:</strong> {corr.summary}{' '}
            <strong>Contagion risk {pct(corr.cross_asset_contagion_risk, 0)}.</strong>
          </>
        ) : (
          <>
            <strong>Live Gemini call</strong> — needs GEMINI_API_KEY on the backend. Charts read the
            committed price snapshot, exactly like the other tabs.
          </>
        )}
      </Insight>

      <Panel title="Analyse an article" wide>
        <div className="controls inline">
          <div className="seg">
            <button className={`chip${mode === 'text' ? ' active' : ''}`} onClick={() => setMode('text')}>
              Text
            </button>
            <button className={`chip${mode === 'image' ? ' active' : ''}`} onClick={() => setMode('image')}>
              Image
            </button>
          </div>
          <div className="seg">
            <button className={`chip${provider === 'google' ? ' active' : ''}`} onClick={() => setProvider('google')}>
              Google
            </button>
            <button className={`chip${provider === 'feather' ? ' active' : ''}`} onClick={() => setProvider('feather')}>
              Feather
            </button>
          </div>
        </div>
        {mode === 'text' ? (
          <div className="news-input">
            <textarea
              rows={7}
              placeholder={
                'Paste a financial news article… e.g. "Bitcoin surges 8% amid Fed rate cut speculation. Goldman sees gold at $2500/oz within 90 days."'
              }
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
        ) : (
          <div className="news-input">
            <input
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => setImage(e.target.files?.[0] ?? null)}
            />
            {image && <Note>{image.name} · {(image.size / 1024).toFixed(0)} KB</Note>}
          </div>
        )}
        <div className="analyze-row">
          <button className="btn primary" onClick={run} disabled={busy}>
            {busy ? 'Analysing…' : 'Analyse news'}
          </button>
        </div>
      </Panel>

      {analysis && (
        <>
          <Panel title="Article overview">
            <div className="stats compact">
              <span className="stat">
                <span className="stat-label">Sentiment</span>
                <span className={`stat-value ${tone}`}>{(meta?.sentiment ?? '—').toUpperCase()}</span>
              </span>
              <span className="stat">
                <span className="stat-label">Color framing</span>
                <span className="stat-value">{(meta?.color_psychology ?? '—').toUpperCase()}</span>
              </span>
              <span className="stat">
                <span className="stat-label">Urgency</span>
                <span className="stat-value">{(meta?.urgency_level ?? '—').toUpperCase()}</span>
              </span>
              <span className="stat">
                <span className="stat-label">Published</span>
                <span className="stat-value">{meta?.publication_date ?? '—'}</span>
              </span>
            </div>
            <Note>{meta?.summary ?? 'No summary returned.'}</Note>
          </Panel>

          <Panel title="Extracted entities">
            {entities?.assets?.length ? (
              <div className="entity-line">
                <span className="entity-label">Assets</span>
                {entities.assets.map((a) => (
                  <span key={a} className="chip active">
                    {nameOf(a)}
                  </span>
                ))}
              </div>
            ) : (
              <Note>No platform assets identified.</Note>
            )}
            {entities?.indicators?.length ? (
              <div className="entity-line">
                <span className="entity-label">Indicators</span>
                {entities.indicators.map((i) => (
                  <span key={i} className="chip">
                    {i}
                  </span>
                ))}
              </div>
            ) : null}
            {entities?.events?.length ? (
              <div className="entity-line">
                <span className="entity-label">Events</span>
                {entities.events.map((e) => (
                  <span key={e} className="chip">
                    {e}
                  </span>
                ))}
              </div>
            ) : null}
            {entities?.numeric_mentions?.length ? (
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Number</th>
                      <th>Context</th>
                      <th>Impact</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entities.numeric_mentions.map((m, i) => (
                      <tr key={i}>
                        <td>{m.value ?? '—'}</td>
                        <td>{m.context ?? '—'}</td>
                        <td>{(m.impact ?? '—').toUpperCase()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </Panel>

          {direct.length > 0 && (
            <Panel title="Direct dependencies" subtitle="Assets most affected, 0-1 day lag" wide>
              <div className="dep-grid">
                {direct.map((d, i) => (
                  <DirectCard key={`${d.asset}-${i}`} dep={d} charts={charts} />
                ))}
              </div>
              <Note>
                Each chart shows the last {direct[0]?.chart_data_needed?.lookback_days ?? 5} trading
                days from the committed snapshot — real prices, not model output.
              </Note>
            </Panel>
          )}

          {indirect.length > 0 && (
            <Panel title="Indirect dependencies" subtitle="Causal chains resolving over 2-7 days" wide>
              {indirect.map((r, i) => {
                const pk = r.affected_assets.find((a) => PLATFORM_KEYS.includes(a.toUpperCase()))
                const chart = pk ? charts[pk.toUpperCase()] : undefined
                return (
                  <div className="rel" key={i}>
                    <Chain chain={r.chain} />
                    <div className="dep-meta">
                      <span>
                        Timeline <em>{num(r.expected_timeline_days, 0)} days</em>
                      </span>
                      <span>
                        Confidence <em>{pct(r.confidence, 0)}</em>
                      </span>
                    </div>
                    <ProbBar value={r.confidence} />
                    {chart && <MiniChart data={chart} />}
                  </div>
                )
              })}
            </Panel>
          )}

          {predictions.length > 0 && (
            <Panel title="Numeric predictions" subtitle="Impact extracted from the numbers in the article" wide>
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Mention</th>
                      <th>Asset</th>
                      <th>Predicted move</th>
                      <th>Timeframe</th>
                      <th>Probability</th>
                    </tr>
                  </thead>
                  <tbody>
                    {predictions.map((p, i) => (
                      <PredictionRow key={i} p={p} />
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          <Panel title="Portfolio correlation analysis" wide>
            <div className="stats compact">
              <span className="stat">
                <span className="stat-label">Correlation</span>
                <span className="stat-value">{(corr?.portfolio_correlation_shift ?? '—').toUpperCase()}</span>
              </span>
              <span className="stat">
                <span className="stat-label">Contagion risk</span>
                <span className="stat-value">{pct(corr?.cross_asset_contagion_risk ?? null, 0)}</span>
              </span>
              <span className="stat">
                <span className="stat-label">Diversification</span>
                <span className="stat-value">{(corr?.diversification_impact ?? '—').toUpperCase()}</span>
              </span>
            </div>
            <Note>{corr?.summary ?? 'No correlation read returned.'}</Note>
          </Panel>
        </>
      )}
    </>
  )
}