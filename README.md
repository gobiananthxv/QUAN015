# 🧠 ML-Based Market Regime Detection

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-1.3%2B-orange?logo=scikit-learn&logoColor=white)
![hmmlearn](https://img.shields.io/badge/hmmlearn-0.3%2B-green)
![License](https://img.shields.io/badge/License-MIT-purple)
![Tests](https://img.shields.io/badge/Tests-50%20passing-brightgreen)

**Unsupervised Machine Learning for Dynamic Financial Market Classification**

*Automatically detects Bull, Bear, High-Volatility, and Sideways market regimes using Hidden Markov Models (HMM) and Gaussian Mixture Models (GMM) — then adjusts trading strategy parameters in real time.*

</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [How It Works](#-how-it-works)
- [Project Structure](#-project-structure)
- [Modules At a Glance](#-modules-at-a-glance)
- [Feature Engineering](#-feature-engineering)
- [Models](#-models)
- [Regime Labels](#-regime-labels)
- [Adaptive Strategy](#-adaptive-strategy)
- [Walk-Forward Backtest](#-walk-forward-backtest)
- [Visualizations](#-visualizations)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Single Command — Run Everything](#-single-command--run-everything)
- [CLI Reference](#-cli-reference)
- [Python API](#-python-api)
- [Output Files](#-output-files)
- [Configuration](#-configuration)
- [Testing](#-testing)
- [HMM vs GMM](#-hmm-vs-gmm)
- [Design Decisions](#-design-decisions)
- [Extending the System](#-extending-the-system)

---

## 🔍 Overview

Traditional algorithmic trading strategies apply fixed rules regardless of market conditions — a trend-following system that works in a bull market will bleed in a bear market. This project solves that by **letting the data define the market state**.

Using **unsupervised machine learning**, the system:

1. Computes 7 rolling financial features (returns, volatility, SMA/EMA distances)
2. Feeds them into either a **Hidden Markov Model** or a **Gaussian Mixture Model**
3. Automatically identifies latent market regimes (no manual labelling needed)
4. Assigns human-readable names (**Bull / Bear / High-Volatility / Sideways**) based on cluster statistics
5. Adjusts position size, stop-loss, take-profit, and signal type for each regime
6. Validates with a **walk-forward backtest** (zero look-ahead bias)
7. Produces a full dashboard with regime-overlaid price charts and equity curves

---

## ⚙️ How It Works

```
Yahoo Finance
     │
     ▼
┌─────────────┐     ┌──────────────────────┐     ┌───────────────┐
│ DataLoader  │────▶│ FeatureEngineer      │────▶│  StandardScale│
│ (OHLCV)     │     │ 7 rolling signals    │     │  r (fit/xform)│
└─────────────┘     └──────────────────────┘     └───────┬───────┘
                                                         │
                              ┌──────────────────────────┤
                              │                          │
                              ▼                          ▼
                     ┌────────────────┐       ┌─────────────────┐
                     │  HMMRegime     │       │  GMMRegime      │
                     │  Model         │       │  Model          │
                     │  (hmmlearn)    │       │  (scikit-learn) │
                     └───────┬────────┘       └────────┬────────┘
                             │                         │
                             └──────────┬──────────────┘
                                        │
                                        ▼
                               ┌─────────────────┐
                               │  RegimeLabeler  │
                               │  Bull / Bear /  │
                               │  High-Vol /     │
                               │  Sideways       │
                               └────────┬────────┘
                                        │
                       ┌────────────────┼────────────────┐
                       │                │                │
                       ▼                ▼                ▼
              ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
              │  Adaptive   │  │  Walk-Forward│  │  Plotter     │
              │  Strategy   │  │  Backtest    │  │  Dashboard   │
              │  (params)   │  │  (P&L)       │  │  (charts)    │
              └─────────────┘  └──────────────┘  └──────────────┘
```

---

## 📁 Project Structure

```
market_regime_detection/
│
├── run_all.py                    ← Single command: runs everything end-to-end
├── main.py                       ← Flexible CLI entry point
├── config.py                     ← All tunable parameters in one place
├── requirements.txt
├── README.md
│
├── data/
│   ├── __init__.py
│   └── data_loader.py            ← yfinance download + CSV caching
│
├── features/
│   ├── __init__.py
│   └── feature_engineering.py   ← 7 financial features + StandardScaler
│
├── models/
│   ├── __init__.py
│   ├── base_model.py             ← Abstract interface (fit/predict/bic)
│   ├── hmm_model.py              ← GaussianHMM via hmmlearn
│   └── gmm_model.py              ← GaussianMixture via scikit-learn
│
├── regime/
│   ├── __init__.py
│   ├── detector.py               ← Orchestrates full pipeline → RegimeResult
│   └── labeler.py                ← Cluster ID → semantic name
│
├── strategy/
│   ├── __init__.py
│   └── adaptive_strategy.py      ← Per-regime trading params
│
├── backtest/
│   ├── __init__.py
│   └── walk_forward.py           ← Rolling walk-forward validation
│
├── visualization/
│   ├── __init__.py
│   └── plotter.py                ← 4-panel dashboard + distribution chart
│
├── tests/
│   ├── __init__.py
│   ├── test_feature_engineering.py
│   ├── test_models.py
│   ├── test_labeler.py
│   ├── test_strategy.py
│   └── test_walk_forward.py
│
└── output/                       ← Auto-created by run_all.py
    ├── *.csv                     ← Exported data files
    └── plots/
        └── *.png                 ← Saved chart images
```

---

## 🧩 Modules At a Glance

| Module | Class / Function | Responsibility |
|--------|-----------------|----------------|
| `data/data_loader.py` | `DataLoader` | Downloads OHLCV via yfinance, caches as CSV |
| `features/feature_engineering.py` | `FeatureEngineer` | Computes 7 rolling features, fits `StandardScaler` |
| `models/base_model.py` | `BaseRegimeModel` | Abstract interface — `fit`, `predict`, `predict_proba`, `bic` |
| `models/hmm_model.py` | `HMMRegimeModel` | `GaussianHMM` with Viterbi decoding + BIC model selection |
| `models/gmm_model.py` | `GMMRegimeModel` | `GaussianMixture` with soft probabilities + BIC model selection |
| `regime/labeler.py` | `RegimeLabeler` | Maps cluster IDs → Bull / Bear / High-Volatility / Sideways |
| `regime/detector.py` | `RegimeDetector` | Wires all steps, returns `RegimeResult` dataclass |
| `strategy/adaptive_strategy.py` | `AdaptiveStrategy` | Returns position size, stops, signal type per regime |
| `backtest/walk_forward.py` | `WalkForwardBacktest` | Rolling train-test validation, Sharpe/CAGR/drawdown |
| `visualization/plotter.py` | `RegimePlotter` | 4-panel dashboard and distribution bar chart |
| `run_all.py` | `main()` | Single-command full pipeline runner |
| `main.py` | `main()` | Flexible CLI with all flags |
| `config.py` | constants + dataclasses | Centralised configuration |

---

## 📊 Feature Engineering

Seven signals are computed from daily OHLCV data and fed into both HMM and GMM:

| # | Feature | Formula | Why It Matters |
|---|---------|---------|----------------|
| 1 | `log_return_5d` | `Σ log(Pₜ/Pₜ₋₁)` over 5 days | Short-term momentum |
| 2 | `log_return_21d` | `Σ log(Pₜ/Pₜ₋₁)` over 21 days | Medium-term trend direction |
| 3 | `realized_vol_21d` | `std(daily log returns, 21d) × √252` | Annualised volatility regime |
| 4 | `sma50_dist` | `(Price − SMA₅₀) / SMA₅₀` | Distance from medium-term trend |
| 5 | `sma200_dist` | `(Price − SMA₂₀₀) / SMA₂₀₀` | Distance from long-term trend |
| 6 | `ema_ratio` | `EMA₁₂ / EMA₂₆` | MACD-like momentum signal |
| 7 | `high_vol_flag` | `1 if vol > 2× long-term median` | Binary volatility spike indicator |

All features are normalised with `sklearn.preprocessing.StandardScaler` before being passed to any model (mean = 0, std = 1 per feature).

---

## 🤖 Models

### Hidden Markov Model (HMM)

```
hmmlearn.hmm.GaussianHMM
```

- Models market regimes as **latent (hidden) states** in a sequential process
- Each state emits observations drawn from a multivariate Gaussian
- Captures **regime persistence** via a learnable transition matrix `P[i→j]`
- Uses **Viterbi decoding** to find the most likely state sequence
- Auto-selects `n_components ∈ {2, 3, 4, 5}` via **BIC** across 5 random restarts

**What you get from the HMM:**
- State sequence (hard labels)
- Posterior probabilities (soft labels, forward-backward)
- Transition matrix — probability of staying in or switching regime
- Emission means — average feature values per regime

### Gaussian Mixture Model (GMM)

```
sklearn.mixture.GaussianMixture
```

- Models the joint feature distribution as a **weighted sum of Gaussians**
- No temporal structure — each day is classified independently
- Returns **soft posterior probabilities** (useful for transition-period signals)
- Auto-selects `n_components ∈ {2, 3, 4, 5}` via **BIC**

**What you get from the GMM:**
- Hard cluster labels (`argmax` of posteriors)
- Soft probabilities per component
- Mixture weights (prior probability of each regime)
- Full covariance matrices per component

> **BIC auto-selection** prevents overfitting — the model with the fewest components that still explains the data well is selected.

---

## 🏷️ Regime Labels

Raw cluster IDs (0, 1, 2, …) are automatically named using cluster statistics.

### Algorithm

For each cluster, compute:
- **Annualised return** = `mean(log_return_21d) × (252 / 21)`
- **Annualised volatility** = `mean(realized_vol_21d)` (already annualised)

Then apply priority-based greedy assignment:

| Priority | Label | Condition |
|----------|-------|-----------|
| 1 (highest) | **High-Volatility** | `ann_vol > 20%` |
| 2 | **Bear** | `ann_return < −2%` |
| 3 | **Bull** | `ann_return > 5%` |
| 4 | **Sideways** | Everything else |

If two clusters qualify for the same label, the cluster with the more extreme characteristic wins. No two clusters share a label.

---

## 📐 Adaptive Strategy

The `AdaptiveStrategy` maps the current regime to a set of trading parameters:

| Regime | Position Size | Stop Loss | Take Profit | Leverage | Signal Type |
|--------|:------------:|:---------:|:-----------:|:--------:|-------------|
| **Bull** | 100% | 5% | 20% | 1.0× | Trend-following |
| **Bear** | 30% | 2% | 8% | 0.3× | Mean-reversion / Cash |
| **High-Volatility** | 50% | 3% | 10% | 0.5× | Volatility breakout |
| **Sideways** | 70% | 4% | 12% | 0.7× | Range-bound / Oscillators |
| **Unknown** | 50% | 3% | 10% | 0.5× | Neutral (fallback) |

All thresholds are configurable in [`config.py`](config.py).

---

## 📈 Walk-Forward Backtest

Simulates realistic out-of-sample performance with **zero look-ahead bias**:

```
├── Training window (252 trading days = 1 year)
│       ↓ fit FeatureEngineer + HMM/GMM here
├── Test window (21 trading days = 1 month)
│       ↓ predict regimes using frozen model
│       ↓ apply AdaptiveStrategy position sizing
│       ↓ compute daily regime-adjusted returns
├── Step forward 21 days → repeat
```

**Key guarantee:** The model and feature scaler are fitted **exclusively** on training data. The combined train+test slice is only used for rolling-feature lookback continuity — the model never sees test labels during training.

**Output metrics:**
| Metric | Description |
|--------|-------------|
| CAGR | Compound Annual Growth Rate |
| Sharpe Ratio | Annualised excess return / volatility |
| Max Drawdown | Worst peak-to-trough decline |
| Total Return | Cumulative P&L across all folds |

---

## 📉 Visualizations

`run_all.py` generates a **4-panel dashboard** for each model:

```
┌──────────────────────────────────────────────────────────┐
│  Panel 1: Price chart with regime colour bands           │
│  (green = Bull, red = Bear, orange = High-Vol,           │
│   blue = Sideways)                                       │
├──────────────────────────────────────────────────────────┤
│  Panel 2: Feature heatmap (normalized, green=high)       │
│  Shows all 7 features over time                          │
├──────────────────────────────────────────────────────────┤
│  Panel 3: HMM transition matrix heatmap                  │
│           OR GMM component weight bar chart              │
├──────────────────────────────────────────────────────────┤
│  Panel 4: Equity curve — Strategy vs Buy & Hold          │
│  (only when --backtest is run)                           │
└──────────────────────────────────────────────────────────┘
```

Plus a standalone **regime distribution bar chart** showing days/percentage per regime.

---

## 🛠 Installation

### Prerequisites

- Python 3.10 or higher
- pip

### Install

```bash
git clone <your-repo-url>
cd market_regime_detection

pip install -r requirements.txt
```

`requirements.txt`:
```
yfinance>=0.2.40
hmmlearn>=0.3.0
scikit-learn>=1.3.0
pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
plotly>=5.15.0
seaborn>=0.12.0
scipy>=1.11.0
joblib>=1.3.0
```

> **Note for Linux/Ubuntu:** `hmmlearn` needs a C compiler:
> ```bash
> sudo apt install build-essential
> ```

---

## ⚡ Quick Start

```bash
# Detect regimes on SPY using HMM, show plots
python main.py --ticker SPY --model hmm --start-date 2010-01-01 --plot

# Compare both models
python main.py --ticker SPY --model both --start-date 2010-01-01 --plot

# Add walk-forward backtest
python main.py --ticker SPY --model hmm --backtest --plot
```

---

## 🚀 Single Command — Run Everything

```bash
python run_all.py
```

This single command executes all 7 pipeline steps and saves all outputs:

```bash
# Custom ticker and date range
python run_all.py --ticker QQQ --start 2015-01-01

# Fix number of regimes (skip BIC auto-select)
python run_all.py --ticker SPY --n-states 3

# Also open interactive plot windows
python run_all.py --ticker SPY --show-plots

# Custom output folder
python run_all.py --ticker SPY --output-dir ./results/

# Re-download fresh data (ignore cache)
python run_all.py --ticker SPY --force-download
```

### What `run_all.py` Does

```
══════════════════════════════════════════════════════════════
  ML Market Regime Detection — Full Pipeline
  Ticker: SPY   Range: 2010-01-01 → today
══════════════════════════════════════════════════════════════

── STEP 1 / 7 — Data Download & Caching ─────────────────────
  ✔  Loaded 3,784 rows  (2010-01-04 → 2026-09-19)
  ✔  Columns: ['open', 'high', 'low', 'close', 'volume']

── STEP 2 / 7 — Feature Engineering ─────────────────────────
  ✔  Feature matrix: 3,584 rows × 7 features
  ✔  Raw features exported → output/SPY_features.csv

── STEP 3 / 7 — HMM Regime Detection ────────────────────────
  ✔  Ticker: SPY  |  Model: HMM  |  N states: 3
  ✔  Current regime: Bull
  ✔  HMM regimes exported → output/SPY_hmm_regimes.csv

── STEP 4 / 7 — GMM Regime Detection ────────────────────────
  ✔  Ticker: SPY  |  Model: GMM  |  N states: 3
  ✔  Current regime: Bull
  ✔  GMM regimes exported → output/SPY_gmm_regimes.csv

── STEP 5 / 7 — Adaptive Strategy Parameters ────────────────
  ✔  [HMM] Bull → position_size: 1.0, stop_loss: 5%, take_profit: 20%
  ✔  Strategy table exported → output/strategy_params.csv

── STEP 6 / 7 — Walk-Forward Backtest (HMM + GMM) ───────────
  ✔  Equity curves exported → output/SPY_hmm_equity.csv
  ✔  Fold results exported  → output/SPY_hmm_folds.csv

── STEP 7 / 7 — Generating Visualizations ───────────────────
  ✔  HMM dashboard → output/plots/SPY_hmm_dashboard.png
  ✔  GMM dashboard → output/plots/SPY_gmm_dashboard.png

ALL DONE  (142.3s)
```

---

## 🖥 CLI Reference

```bash
python main.py [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--ticker` | `SPY` | Yahoo Finance ticker symbol |
| `--model` | `hmm` | `hmm` \| `gmm` \| `both` |
| `--start-date` | `2005-01-01` | Historical data start |
| `--end-date` | today | Historical data end |
| `--n-states` | auto (BIC) | Fix number of hidden states |
| `--plot` | off | Show interactive dashboard |
| `--save-plots DIR` | off | Save PNGs to directory |
| `--backtest` | off | Run walk-forward backtest |
| `--export FILE.csv` | off | Export regime series |
| `--force-download` | off | Re-download ignoring cache |
| `--verbose / -v` | off | Enable DEBUG logging |

### Examples

```bash
# HMM on SPY with plots
python main.py --ticker SPY --model hmm --start-date 2010-01-01 --plot

# Both models + backtest on QQQ
python main.py --ticker QQQ --model both --backtest --start-date 2015-01-01 --plot

# GMM with fixed 4 states, export CSV
python main.py --ticker AAPL --model gmm --n-states 4 --export aapl_regimes.csv

# Headless server mode (save plots, no display)
python main.py --ticker SPY --model both --backtest --save-plots ./plots/

# Debug mode
python main.py --ticker SPY --model hmm --verbose
```

---

## 🐍 Python API

### Regime Detection

```python
from regime.detector import RegimeDetector

# Run HMM detection
detector = RegimeDetector(ticker="SPY", model_type="hmm")
result = detector.run(start="2010-01-01")

# Access results
print(result.summary())            # Full text summary
print(result.current_regime)       # e.g. "Bull"
print(result.n_states)             # e.g. 3
print(result.regime_counts)        # Days per regime
print(result.regime_series.tail()) # Last 5 days with labels
print(result.state_proba.tail())   # Soft probabilities per state
print(result.label_map)            # {0: 'Bull', 1: 'Bear', 2: 'High-Volatility'}
print(result.cluster_stats)        # Per-state mean return & vol
```

### Strategy Parameters

```python
from strategy.adaptive_strategy import AdaptiveStrategy

strategy = AdaptiveStrategy()

# Current regime parameters
params = strategy.get_params("Bull")
# {'position_size': 1.0, 'stop_loss_pct': 0.05, 'take_profit_pct': 0.20,
#  'signal_filter': 'trend_following', 'leverage': 1.0, ...}

# Signal multiplier (= position_size)
mult = strategy.get_signal_multiplier("Bear")  # 0.30

# Apply to entire time series → DataFrame
param_df = strategy.apply_to_series(result.regime_series)

# Summary table
print(strategy.regime_summary())
```

### Walk-Forward Backtest

```python
from backtest.walk_forward import WalkForwardBacktest

bt = WalkForwardBacktest(
    ticker="SPY",
    model_type="hmm",
    train_days=252,   # 1 year training window
    step_days=21,     # 1 month step
)
bt_result = bt.run(start="2010-01-01")

print(bt_result.summary())            # CAGR, Sharpe, MaxDD table
print(bt_result.metrics)              # Dict with strategy + benchmark metrics
print(bt_result.equity_curve.tail())  # Cumulative portfolio value
print(bt_result.benchmark.tail())     # Buy-and-hold cumulative value
print(len(bt_result.fold_results))    # Number of folds
```

### Feature Engineering

```python
from features.feature_engineering import FeatureEngineer
from data.data_loader import DataLoader

loader = DataLoader()
price_df = loader.load("SPY", start="2010-01-01")

fe = FeatureEngineer()
X_scaled, idx = fe.fit_transform(price_df)    # Fit + scale
raw = fe.get_raw_features(price_df)           # Unscaled features

print(raw.describe())   # Stats for each of the 7 features
```

### Visualization

```python
from visualization.plotter import RegimePlotter

plotter = RegimePlotter(save_dir="./plots/", show=True)

# 4-panel dashboard
plotter.plot_dashboard(
    price_df     = result.price_data,
    regime_series= result.regime_series,
    feature_df   = result.feature_data,
    model        = result.model,
    equity_curve = bt_result.equity_curve,  # optional
    benchmark    = bt_result.benchmark,     # optional
    ticker       = "SPY",
    model_type   = "hmm",
)

# Standalone distribution chart
plotter.plot_regime_distribution(result.regime_series, ticker="SPY")
```

### HMM-Specific Properties

```python
result = RegimeDetector(ticker="SPY", model_type="hmm").run("2010-01-01")
model = result.model

print(model.transition_matrix)   # Shape: (n_states, n_states)
print(model.emission_means)      # Shape: (n_states, n_features)
print(model.n_states)            # e.g. 3
print(model.log_likelihood)      # Training log-likelihood
```

### GMM-Specific Properties

```python
result = RegimeDetector(ticker="SPY", model_type="gmm").run("2010-01-01")
model = result.model

print(model.weights)       # Shape: (n_components,)   — mixture priors
print(model.means)         # Shape: (n_components, n_features)
print(model.covariances)   # Shape: (n_components, n_features, n_features)
print(model.aic(X))        # Akaike Information Criterion
print(model.bic(X))        # Bayesian Information Criterion
```

---

## 📂 Output Files

After running `python run_all.py`, the `./output/` directory contains:

| File | Format | Contents |
|------|--------|---------|
| `{TICKER}_features.csv` | CSV | 7 raw features × all trading days |
| `{TICKER}_hmm_regimes.csv` | CSV | Date, regime label, state ID, per-state probabilities |
| `{TICKER}_gmm_regimes.csv` | CSV | Same for GMM |
| `strategy_params.csv` | CSV | Position size, stops, signal type per regime |
| `{TICKER}_hmm_equity.csv` | CSV | Strategy vs buy-and-hold equity curves |
| `{TICKER}_gmm_equity.csv` | CSV | Same for GMM |
| `{TICKER}_hmm_folds.csv` | CSV | Per-fold returns, regimes, train/test dates |
| `{TICKER}_gmm_folds.csv` | CSV | Same for GMM |
| `plots/{TICKER}_hmm_dashboard.png` | PNG | 4-panel HMM dashboard |
| `plots/{TICKER}_gmm_dashboard.png` | PNG | 4-panel GMM dashboard |
| `plots/{TICKER}_regime_distribution.png` | PNG | Regime day-count bar chart |

---

## ⚙️ Configuration

All parameters are in [`config.py`](config.py). Edit this file to tune the system without touching any other code.

```python
# ── Feature windows ─────────────────────────────────────────────────
RETURN_WINDOWS = [5, 21]        # Log return rolling windows (days)
VOLATILITY_WINDOW = 21          # Realized vol window (days)
SMA_WINDOWS = [50, 200]         # SMA distance windows
EMA_SHORT, EMA_LONG = 12, 26   # EMA ratio spans
VOL_SPIKE_MULTIPLIER = 2.0      # High-vol flag threshold (× median vol)

# ── Model hyperparameters ────────────────────────────────────────────
HMMConfig(
    n_components_range = [2, 3, 4, 5],  # BIC sweep range
    covariance_type    = "full",
    n_iter             = 200,
    n_init             = 5,              # Random restarts
)

GMMConfig(
    n_components_range = [2, 3, 4, 5],
    covariance_type    = "full",
    n_init             = 10,
)

# ── Regime labeling thresholds ───────────────────────────────────────
BULL_RETURN_THRESHOLD = 0.05    # Ann. return > 5%  → Bull
BEAR_RETURN_THRESHOLD = -0.02   # Ann. return < -2% → Bear
HIGH_VOL_THRESHOLD    = 0.20    # Ann. vol > 20%    → High-Volatility

# ── Walk-forward settings ────────────────────────────────────────────
WALK_FORWARD_TRAIN_DAYS = 252   # Training window (1 year)
WALK_FORWARD_STEP_DAYS  = 21    # Step size (1 month)
RISK_FREE_RATE          = 0.04  # For Sharpe calculation

# ── Strategy params per regime ───────────────────────────────────────
STRATEGY_PARAMS = {
    "Bull":            {"position_size": 1.00, "stop_loss_pct": 0.05, ...},
    "Bear":            {"position_size": 0.30, "stop_loss_pct": 0.02, ...},
    "High-Volatility": {"position_size": 0.50, "stop_loss_pct": 0.03, ...},
    "Sideways":        {"position_size": 0.70, "stop_loss_pct": 0.04, ...},
}
```

---

## 🧪 Testing

```bash
# Run all 50 tests
python -m pytest tests/ -v

# Individual test suites
python -m pytest tests/test_feature_engineering.py -v   # 9 tests
python -m pytest tests/test_models.py -v                # 18 tests (HMM + GMM)
python -m pytest tests/test_labeler.py -v               # 9 tests
python -m pytest tests/test_strategy.py -v              # 9 tests
python -m pytest tests/test_walk_forward.py -v          # 6 tests

# Coverage report
python -m pytest tests/ --cov=. --cov-report=term-missing
```

### Test Coverage

| Test File | Tests | What Is Verified |
|-----------|:-----:|-----------------|
| `test_feature_engineering.py` | 9 | Shape, NaN-free, scaler mean=0, index alignment, binary flag |
| `test_models.py` | 18 | fit/predict shapes, valid state IDs, transition row-sum=1, BIC finite |
| `test_labeler.py` | 9 | Valid labels, no duplicates, cluster stats columns, not-fitted error |
| `test_strategy.py` | 9 | Param ranges, Bull > Bear position size, unknown fallback, apply_to_series |
| `test_walk_forward.py` | 6 | **No look-ahead bias** (`train_end < test_start`), metrics correctness |

---

## 🆚 HMM vs GMM

| Aspect | HMM | GMM |
|--------|-----|-----|
| **Regime persistence** | ✅ Models transitions between states | ❌ Each day classified independently |
| **Temporal structure** | ✅ Learns how long regimes last | ❌ No temporal memory |
| **Soft probabilities** | ✅ Forward-backward algorithm | ✅ Posterior probabilities |
| **Interpretability** | ✅ Transition matrix shows P(regime switch) | ✅ Mixture weights = regime base rates |
| **Speed** | Slower (EM on sequences) | Faster |
| **Best for** | Trending, persistent markets | Volatile, mean-reverting markets |
| **Overfitting risk** | Moderate | Lower (simpler model) |
| **Label stability** | High (Viterbi path is smooth) | Lower (can flip day-to-day) |

**Recommendation:** Use **HMM as primary** (regime persistence is financially meaningful). Cross-validate with GMM. When both agree → higher confidence in the signal.

---

## 🏗 Design Decisions

### BIC-Based Model Selection
Both models sweep `n_components ∈ {2, 3, 4, 5}` and pick the lowest BIC. This is automatic — no manual tuning required. The Bayesian Information Criterion penalises complexity, so a 5-state model only wins if it genuinely explains the data better.

### Walk-Forward Without Look-Ahead
The feature scaler **and** model are trained only on the training window. The test slice uses `transform()` (not `fit_transform()`) and only sees training-window statistics — the same way a live system would work.

### Priority-Based Greedy Labelling
High-Volatility is assigned first because it is the most actionable signal (risk-off). Bear is next. This prevents a crash period from being mislabelled as "Bull with high vol".

### StandardScaler Before Modelling
Without scaling, `realized_vol_21d` (values ≈ 0.1–0.5) would dominate `sma200_dist` (values ≈ −0.3 to +0.5) purely due to magnitude differences. Scaling gives all features equal weight in the Gaussian covariance.

---

## 🔧 Extending the System

### Add a New Feature

Edit [`features/feature_engineering.py`](features/feature_engineering.py):

```python
FEATURE_NAMES = [
    ...,
    "rsi_14",       # ← add here
]

def _compute_raw_features(self, df):
    ...
    # RSI 14-day
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    features["rsi_14"] = 100 - (100 / (1 + rs))
    ...
```

### Add a New Regime Label

Edit thresholds in [`config.py`](config.py):

```python
BULL_RETURN_THRESHOLD = 0.08    # Raise bar for "Bull"
HIGH_VOL_THRESHOLD    = 0.25    # Raise bar for "High-Volatility"
```

Or add a new label in [`regime/labeler.py`](regime/labeler.py):

```python
_PRIORITY = ["High-Volatility", "Bear", "Bull", "Recovery", "Sideways", "Unknown"]
```

### Add a New Model

Create `models/my_model.py` subclassing `BaseRegimeModel`:

```python
from models.base_model import BaseRegimeModel

class MyRegimeModel(BaseRegimeModel):
    def fit(self, X): ...
    def predict(self, X): ...
    def predict_proba(self, X): ...
    def bic(self, X): ...
    @property
    def n_states(self): ...
```

Register it in [`regime/detector.py`](regime/detector.py):

```python
def _build_model(self):
    if self.model_type == "my_model":
        return MyRegimeModel()
    ...
```

### Override Strategy Parameters

```python
from strategy.adaptive_strategy import AdaptiveStrategy

custom = {
    "Bull": {"position_size": 0.80, "stop_loss_pct": 0.06},
    "Bear": {"position_size": 0.10},
}
strategy = AdaptiveStrategy(custom_params=custom)
```

---

## 📝 License

MIT License — free to use, modify, and distribute.

---

## 🙏 Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| [yfinance](https://github.com/ranaroussi/yfinance) | ≥ 0.2.40 | Market data download |
| [hmmlearn](https://hmmlearn.readthedocs.io/) | ≥ 0.3.0 | Hidden Markov Models |
| [scikit-learn](https://scikit-learn.org/) | ≥ 1.3.0 | GMM + StandardScaler |
| [pandas](https://pandas.pydata.org/) | ≥ 2.0.0 | Time-series data frames |
| [numpy](https://numpy.org/) | ≥ 1.24.0 | Numerical computation |
| [matplotlib](https://matplotlib.org/) | ≥ 3.7.0 | Static plotting |
| [seaborn](https://seaborn.pydata.org/) | ≥ 0.12.0 | Heatmaps |
| [scipy](https://scipy.org/) | ≥ 1.11.0 | Statistical utilities |

---

<div align="center">

Built with Python 🐍 · Powered by `hmmlearn` + `scikit-learn` · Market data via `yfinance`

</div>
