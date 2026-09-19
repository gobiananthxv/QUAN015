# ML-Based Market Regime Detection

A production-ready Python system that uses **unsupervised machine learning** to dynamically classify financial market regimes — **Bull**, **Bear**, **High-Volatility**, and **Sideways** — and automatically adjusts trading strategy parameters based on the detected state.

Two complementary models are implemented:
- **Hidden Markov Model (HMM)** via `hmmlearn` — captures regime *persistence* and transition probabilities
- **Gaussian Mixture Model (GMM)** via `scikit-learn` — provides soft regime probabilities and mixture weights

---

## Architecture

```
market_regime_detection/
├── config.py                     # Centralized configuration
├── data/
│   └── data_loader.py            # yfinance download + CSV caching
├── features/
│   └── feature_engineering.py   # 7-feature matrix + StandardScaler
├── models/
│   ├── base_model.py             # Abstract interface
│   ├── hmm_model.py              # GaussianHMM (hmmlearn)
│   └── gmm_model.py              # GaussianMixture (scikit-learn)
├── regime/
│   ├── detector.py               # Full pipeline orchestration
│   └── labeler.py                # Semantic regime naming
├── strategy/
│   └── adaptive_strategy.py      # Parameter adjustment per regime
├── backtest/
│   └── walk_forward.py           # Walk-forward validation (no lookahead)
├── visualization/
│   └── plotter.py                # 4-panel dashboard
├── tests/                        # pytest unit tests
└── main.py                       # CLI entry point
```

---

## Features

### Feature Matrix (7 signals fed into HMM/GMM)

| Feature | Description |
|---------|-------------|
| `log_return_5d` | 5-day rolling log return |
| `log_return_21d` | 21-day rolling log return |
| `realized_vol_21d` | 21-day realized volatility (annualized) |
| `sma50_dist` | % distance from 50-day SMA |
| `sma200_dist` | % distance from 200-day SMA |
| `ema_ratio` | EMA-12 / EMA-26 (MACD proxy) |
| `high_vol_flag` | Binary: vol > 2× long-term median |

All features are `StandardScaler`-normalized before model training.

### Regime Labeling

Raw cluster IDs (0, 1, 2, …) are automatically named using cluster statistics:

| Regime | Condition |
|--------|-----------|
| **Bull** | Annualized return > 5%, vol moderate |
| **Bear** | Annualized return < –2% |
| **High-Volatility** | Annualized vol > 20% |
| **Sideways** | Everything else |

### Adaptive Strategy Parameters

| Regime | Position Size | Stop Loss | Take Profit | Signal Type |
|--------|:------------:|:---------:|:-----------:|-------------|
| Bull | 100% | 5% | 20% | Trend-following |
| Bear | 30% | 2% | 8% | Mean-reversion |
| High-Volatility | 50% | 3% | 10% | Volatility breakout |
| Sideways | 70% | 4% | 12% | Range-bound |

---

## Installation

```bash
pip install -r requirements.txt
```

> **Note:** `hmmlearn` requires a C compiler. On Ubuntu: `sudo apt install build-essential`

---

## Quick Start

### Detect regimes (HMM, default SPY)
```bash
python main.py --ticker SPY --model hmm --start-date 2010-01-01 --plot
```

### Compare both models side-by-side
```bash
python main.py --ticker QQQ --model both --plot
```

### Run walk-forward backtest
```bash
python main.py --ticker SPY --model hmm --backtest --start-date 2010-01-01
```

### Fix number of states + export CSV
```bash
python main.py --ticker AAPL --model gmm --n-states 3 --export regimes.csv
```

### Save plots to disk (headless / server mode)
```bash
python main.py --ticker SPY --model both --backtest --save-plots ./plots/
```

---

## Python API

```python
from regime.detector import RegimeDetector
from strategy.adaptive_strategy import AdaptiveStrategy

# Run detection
detector = RegimeDetector(ticker="SPY", model_type="hmm")
result = detector.run(start="2010-01-01")

print(result.summary())
# Ticker     : SPY
# Model      : HMM
# N states   : 3
# Current    : Bull
# ...

# Get current strategy parameters
strategy = AdaptiveStrategy()
params = strategy.get_params(result.current_regime)
print(params)
# {'position_size': 1.0, 'stop_loss_pct': 0.05, ...}

# Walk-forward backtest
from backtest.walk_forward import WalkForwardBacktest
bt = WalkForwardBacktest(ticker="SPY", model_type="hmm")
bt_result = bt.run(start="2010-01-01")
print(bt_result.summary())
```

---

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## HMM vs GMM: When to Use Which?

| Aspect | HMM | GMM |
|--------|-----|-----|
| Regime persistence | ✅ Models sequential transitions | ❌ Treats each day independently |
| Soft probabilities | ✅ Forward-backward algorithm | ✅ Posterior probabilities |
| Interpretability | ✅ Transition matrix | ✅ Component weights |
| Computation speed | Slower (EM on sequences) | Faster |
| Best for | Trending/persistent markets | Volatile, non-persistent markets |

**Recommendation:** Use HMM as the primary model. Cross-validate with GMM.

---

## Configuration

All parameters are in [`config.py`](config.py):
- `RETURN_WINDOWS`, `VOLATILITY_WINDOW`, `SMA_WINDOWS` — feature windows
- `HMMConfig`, `GMMConfig` — model hyperparameters
- `STRATEGY_PARAMS` — per-regime position/risk settings
- `WALK_FORWARD_TRAIN_DAYS`, `WALK_FORWARD_STEP_DAYS` — backtest settings
- `REGIME_COLORS` — visualization palette

---

## License

MIT
