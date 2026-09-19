import { useEffect, useState } from 'react'
import { api, type Asset, type SnapshotEntry, type StrategyInfo } from './api'
import { ChatPanel } from './chat/ChatPanel'
import { ErrorState, Loading } from './components/Common'
import { PeriodBar } from './components/PeriodBar'
import { PageProvider } from './page/pageContext'
import { PeriodProvider } from './period'
import { Backtest } from './views/Backtest'
import { Compare } from './views/Compare'
import { Correlation } from './views/Correlation'
import { NewsSentiment } from './views/NewsSentiment'
import { Overview } from './views/Overview'
import { Research } from './views/Research'
import { Risk } from './views/Risk'
import './App.css'

const TABS = ['Overview', 'Risk', 'Correlation', 'Backtest', 'Compare', 'Research', 'News Sentiment'] as const
type Tab = (typeof TABS)[number]

const PAGE_SUFFIX: Record<Tab, string> = {
  Overview: 'Price & Trend',
  Risk: 'Risk & Volatility',
  Correlation: 'Cross-Asset Correlation',
  Backtest: 'Backtest & Benchmark',
  Compare: 'Strategy Comparison',
  Research: 'Robustness Research',
  'News Sentiment': 'News Sentiment Analysis',
}

// These tabs are inherently cross-asset: the asset picker does not apply, and
// the chatbot's `selected_asset` marker becomes CROSS.
const CROSS_ASSET_TABS: readonly Tab[] = ['Correlation', 'News Sentiment'] as const

export default function App() {
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [snapshot, setSnapshot] = useState<SnapshotEntry[]>([])
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [asset, setAsset] = useState('NVDA')
  const [tab, setTab] = useState<Tab>('Overview')
  const [chatOpen, setChatOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshNote, setRefreshNote] = useState<string | null>(null)
  const [dataVersion, setDataVersion] = useState(0)

  const boot = () => {
    setError(null)
    Promise.all([api.assets(), api.strategies()])
      .then(([a, s]) => {
        // Default to empty arrays rather than trusting the payload's shape. A
        // stale backend serving an older schema should degrade to a missing
        // freshness line, not a blank page with a console error.
        setAssets(a.assets ?? [])
        setSnapshot(a.snapshot ?? [])
        setStrategies(s.strategies ?? [])
      })
      .catch((e) => setError(e.message))
  }

  /**
   * The only action in the app that reaches the market-data provider.
   * Bumping `dataVersion` remounts the active view so it refetches — otherwise
   * the page would keep showing figures computed from the previous snapshot.
   */
  const refreshData = () => {
    setRefreshing(true)
    setRefreshNote(null)
    api
      .refreshData()
      .then((r) => {
        setSnapshot(r.snapshot ?? [])
        setDataVersion((v) => v + 1)
        // Say plainly what happened. "Already current" is a real outcome for
        // daily data, not a failure, and hiding it would make the button feel
        // broken when pressed twice.
        const updated = r.updated?.length ?? 0
        const skipped = r.skipped?.length ?? 0
        const failed = r.failed?.length ?? 0
        setRefreshNote(
          failed
            ? `Updated ${updated}, failed ${failed}: ${r.failed[0].error}`
            : updated === 0 && skipped
              ? `Already current — daily bars, fetched under a day ago.`
              : `Updated ${updated} asset${updated === 1 ? '' : 's'} from the provider.`,
        )
      })
      .catch((e) => setRefreshNote(`Refresh failed — ${e.message}`))
      .finally(() => setRefreshing(false))
  }

  useEffect(boot, [])

  if (error) return <div className="app"><ErrorState error={error} onRetry={boot} /></div>
  if (!assets) return <div className="app"><Loading what="the platform" /></div>

  // Correlation and News Sentiment are inherently cross-asset, so the asset
  // picker does not apply to them. News analysis maps the article onto whatever
  // platform assets it mentions, independent of the tab's selected asset.
  const showAssetPicker = tab !== 'Correlation' && tab !== 'News Sentiment'

  // Page identity handed to the chatbot: the visible asset (plus its display
  // name) and the tab's section label. Correlation / News Sentiment are marked
  // CROSS because the asset picker does not apply to them.
  const assetMeta = assets.find((a) => a.key === asset)
  const displayName = (assetMeta?.name ?? asset).replace(/ Future\(s\)/, '').trim()
  const pageAsset = CROSS_ASSET_TABS.includes(tab) ? 'CROSS' : asset
  const pageName = CROSS_ASSET_TABS.includes(tab)
    ? PAGE_SUFFIX[tab]
    : `${displayName} — ${PAGE_SUFFIX[tab]}`

  // Latest bar across the snapshot — how current the whole platform is.
  const asOf = snapshot
    .map((s) => s.end)
    .filter((d): d is string => Boolean(d))
    .sort()
    .at(-1)
  const totalRows = snapshot.reduce((n, s) => n + (s.rows ?? 0), 0)

  // Widest range any asset covers — the outer limits for the period picker.
  const starts = snapshot.map((s) => s.start).filter(Boolean) as string[]
  const ends = snapshot.map((s) => s.end).filter(Boolean) as string[]
  const bounds = {
    start: starts.length ? starts.sort()[0] : undefined,
    end: ends.length ? ends.sort().at(-1) : undefined,
  }

  return (
    <PageProvider pageId={tab.replace(/ /g, '-').toLowerCase()} pageName={pageName} asset={pageAsset}>
    <PeriodProvider bounds={bounds}>
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <h1>QMAFIB</h1>
          <p>Quantitative Multi-Asset Financial Intelligence &amp; Backtesting</p>
        </div>

        <div className="pickers">
          {showAssetPicker && (
            <div className="asset-tabs">
              {assets.map((a) => (
                <button
                  key={a.key}
                  className={`asset-tab${asset === a.key ? ' active' : ''}`}
                  onClick={() => setAsset(a.key)}
                  title={`${a.name} (${a.ticker}) · ${a.asset_class} · annualised over ${a.ann_factor} days`}
                >
                  {a.key}
                  <small>{a.asset_class}</small>
                </button>
              ))}
            </div>
          )}
          <button
            className="btn chatbot-toggle"
            onClick={() => setChatOpen((o) => !o)}
            title="Ask the assistant about the current page"
          >
            💬 Chatbot
          </button>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t} className={`tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>

      <div className="databar">
        <div className="databar-left">
          <span className="dot" aria-hidden="true" />
          <span>
            Data as of <strong>{asOf ?? '—'}</strong>
          </span>
          <span className="databar-sep">·</span>
          <span>{totalRows.toLocaleString()} bars from a committed snapshot</span>
          <span
            className="databar-hint"
            title="Every calculation reads a snapshot committed to the repository, never a live request. That is what makes a backtest reproducible — and it means the platform works with no internet connection. Refresh to pull new prices from the provider."
          >
            why?
          </span>
        </div>
        <div className="databar-right">
          {refreshNote && <span className="databar-note">{refreshNote}</span>}
          <button className="btn small" onClick={refreshData} disabled={refreshing}>
            {refreshing ? 'Fetching…' : '↻ Refresh data'}
          </button>
        </div>
      </div>

      <PeriodBar />

      <div className="disclaimer">
        <strong>Research tool, not investment advice.</strong> Every figure is computed
        from historical data. Backtested performance is not a prediction of future returns.
      </div>

      <main className="grid" key={dataVersion}>
        {tab === 'Overview' && <Overview asset={asset} />}
        {tab === 'Risk' && <Risk asset={asset} />}
        {tab === 'Correlation' && <Correlation />}
        {tab === 'Backtest' && <Backtest asset={asset} strategies={strategies} />}
        {tab === 'Compare' && <Compare asset={asset} strategies={strategies} />}
        {tab === 'Research' && <Research asset={asset} strategies={strategies} />}
        {tab === 'News Sentiment' && <NewsSentiment />}
      </main>

      <footer>
        Data: Yahoo Finance · Signals execute at the next bar's open with commission
        and slippage · Buy-and-hold pays the same costs
      </footer>
    </div>
    </PeriodProvider>
    <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
    </PageProvider>
  )
}
