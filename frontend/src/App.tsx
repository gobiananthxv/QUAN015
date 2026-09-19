import { useEffect, useState } from 'react'
import { api, type Asset, type StrategyInfo } from './api'
import { ErrorState, Loading } from './components/Common'
import { Backtest } from './views/Backtest'
import { Correlation } from './views/Correlation'
import { Overview } from './views/Overview'
import { Research } from './views/Research'
import { Risk } from './views/Risk'
import './App.css'

const TABS = ['Overview', 'Risk', 'Correlation', 'Backtest', 'Research'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [asset, setAsset] = useState('NVDA')
  const [tab, setTab] = useState<Tab>('Overview')
  const [error, setError] = useState<string | null>(null)

  const boot = () => {
    setError(null)
    Promise.all([api.assets(), api.strategies()])
      .then(([a, s]) => {
        setAssets(a.assets)
        setStrategies(s.strategies)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(boot, [])

  if (error) return <div className="app"><ErrorState error={error} onRetry={boot} /></div>
  if (!assets) return <div className="app"><Loading what="the platform" /></div>

  // Correlation is inherently cross-asset, so the asset picker does not apply.
  const showAssetPicker = tab !== 'Correlation'

  return (
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
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t} className={`tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>

      <div className="disclaimer">
        <strong>Research tool, not investment advice.</strong> Every figure is computed
        from historical data. Backtested performance is not a prediction of future returns.
      </div>

      <main className="grid">
        {tab === 'Overview' && <Overview asset={asset} />}
        {tab === 'Risk' && <Risk asset={asset} />}
        {tab === 'Correlation' && <Correlation />}
        {tab === 'Backtest' && <Backtest asset={asset} strategies={strategies} />}
        {tab === 'Research' && <Research asset={asset} strategies={strategies} />}
      </main>

      <footer>
        Data: Yahoo Finance · Signals execute at the next bar's open with commission
        and slippage · Buy-and-hold pays the same costs
      </footer>
    </div>
  )
}
