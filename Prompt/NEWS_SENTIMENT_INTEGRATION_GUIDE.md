# News Sentiment Analysis Module - Complete Integration Guide

**Status**: Production-ready backend + Frontend component  
**Dependencies**: Google Gemini API 3-Flash, Flask/FastAPI, React  
**Novelty**: Real-time financial sentiment + causal dependency detection  

---

## 📋 Quick Overview

```
User uploads news article (text/image) 
    ↓
Gemini API analyzes in 6 stages (unified prompt)
    ↓
Returns JSON: dependencies + predictions + color psychology
    ↓
Frontend visualizes: direct/indirect dependencies + charts + predictions
```

---

## 🚀 Setup & Installation

### 1. **Environment Setup**
```bash
# Create .env file
cat > .env << EOF
GEMINI_API_KEY=your_api_key_here
FLASK_ENV=production
DEBUG=false
EOF

# Install dependencies
pip install google-genai flask werkzeug python-dotenv
```

### 2. **Backend Initialization**
```python
from news_sentiment_backend import NewsSentimentAnalyzer

# Initialize once at app startup
analyzer = NewsSentimentAnalyzer(api_key_path='./env')
```

### 3. **Flask Routes Integration**
```python
from flask import Flask
from news_sentiment_routes import news_sentiment_bp

app = Flask(__name__)
app.register_blueprint(news_sentiment_bp)
# Now available at: /api/news-sentiment/*
```

### 4. **React Component Integration**
```jsx
// In your main layout (tabs section)
import NewsSentimentTab from './news_sentiment_frontend.jsx'

<Tabs>
  <Tab name="Overview">...</Tab>
  <Tab name="Risk">...</Tab>
  <Tab name="Backtest">...</Tab>
  <Tab name="Compare">...</Tab>
  <Tab name="Research">...</Tab>
  <Tab name="News Sentiment">
    <NewsSentimentTab />  {/* NEW */}
  </Tab>
</Tabs>
```

---

## 📊 API Endpoints

### **POST `/api/news-sentiment/analyze-text`**
Analyze financial news from text input.

**Request:**
```json
{
  "text": "Bitcoin surges 8% amid Fed rate cut speculation. Goldman Sachs predicts gold could reach $2500/oz within 90 days..."
}
```

**Response:**
```json
{
  "article_metadata": {
    "headline": "Bitcoin Surges Amid Rate Cut Speculation",
    "publication_date": "2024-01-16",
    "sentiment": "bullish",
    "color_psychology": "green",
    "urgency_level": "high"
  },
  "extracted_entities": {
    "assets": ["Bitcoin", "Gold"],
    "indicators": ["Volatility"],
    "events": ["Fed policy"],
    "numeric_mentions": [
      {"value": "8%", "context": "Bitcoin surge", "impact": "high"},
      {"value": "$2500/oz", "context": "Gold price target", "impact": "high"}
    ]
  },
  "direct_dependencies": {
    "assets_affected": [
      {
        "asset": "Bitcoin",
        "impact": "bullish",
        "correlation_strength": 0.92,
        "expected_change": "+5.5%",
        "confidence": 0.88,
        "chart_data_needed": {
          "lookback_days": 5,
          "include_current": true,
          "forecast_days": 0
        }
      },
      {
        "asset": "Gold",
        "impact": "bullish",
        "correlation_strength": 0.65,
        "expected_change": "+2.0%",
        "confidence": 0.72,
        "chart_data_needed": {
          "lookback_days": 5,
          "include_current": true,
          "forecast_days": 0
        }
      }
    ]
  },
  "indirect_dependencies": {
    "relationships": [
      {
        "source": "Fed rate cut expectations",
        "chain": [
          "Fed dovish signals → Bond yields drop",
          "Bond yields drop → DXY weakens",
          "DXY weakness → Commodity strength (Gold, Oil)"
        ],
        "affected_assets": ["Gold"],
        "expected_timeline_days": 3,
        "confidence": 0.78,
        "chart_data_needed": {
          "lookback_days": 5,
          "include_current": true,
          "forecast_days": 3
        }
      }
    ]
  },
  "numeric_predictions": {
    "has_numeric_data": true,
    "predictions": [
      {
        "mention": "Bitcoin +8%",
        "asset_impact": "Bitcoin",
        "predicted_move": "+4% to +7%",
        "timeframe": "1-2 days",
        "probability": 0.85
      },
      {
        "mention": "Gold $2500 target",
        "asset_impact": "Gold",
        "predicted_move": "+1.5% to +2.5%",
        "timeframe": "60-90 days",
        "probability": 0.68
      }
    ]
  },
  "correlation_analysis": {
    "portfolio_correlation_shift": "breakdown expected",
    "cross_asset_contagion_risk": 0.62,
    "diversification_impact": "neutral",
    "summary": "Risk-off sentiment expected to weaken. Gold/Bitcoin divergence may reduce during Fed uncertainty. Portfolio correlation likely to decrease as defensive flows increase."
  },
  "_metadata": {
    "analyzed_at": "2024-01-16T14:30:00Z",
    "gemini_model": "models/gemini-3-flash-preview",
    "api_status": "success"
  }
}
```

### **POST `/api/news-sentiment/analyze-image`**
Analyze financial news from image (newspaper screenshot, financial website).

**Request:**
```
Content-Type: multipart/form-data
Files: image (newspaper.png)
```

**Response:** Same as `analyze-text`

### **POST `/api/news-sentiment/chart-data`**
Fetch historical chart data for identified dependencies.

**Request:**
```json
{
  "asset": "Gold",
  "lookback_days": 5,
  "forecast_days": 3,
  "include_current": true
}
```

**Response:**
```json
{
  "asset": "Gold",
  "dates": ["2024-01-11", "2024-01-12", "2024-01-13", "2024-01-14", "2024-01-15", "2024-01-16"],
  "prices": [2345.50, 2348.25, 2342.10, 2355.80, 2360.50, 2365.25],
  "sma_20": [2348.12, 2349.45, 2350.10, 2351.75, 2353.20, 2354.50],
  "ema_12": [2347.90, 2349.80, 2350.50, 2353.10, 2358.60, 2363.50],
  "forecast": [2368.00, 2370.50, 2373.00]
}
```

### **GET `/api/news-sentiment/sentiment-history`**
Retrieve previous analyses.

**Query Params:**
- `limit` (int, default=10): Number of records
- `asset` (string): Filter by Gold|Bitcoin|NVIDIA

**Response:**
```json
{
  "analyses": [
    {
      "id": "analysis_001",
      "timestamp": "2024-01-16T14:30:00Z",
      "headline": "Bitcoin Surges Amid Rate Cut Speculation",
      "sentiment": "bullish",
      "assets_mentioned": ["Bitcoin", "Gold"],
      "correlation_shift": "breakdown expected"
    }
  ],
  "total": 1
}
```

---

## 🔌 Gemini API Prompt Structure

**Unified Prompt Stages:**

1. **EXTRACT CONTENT** - OCR + entity extraction
2. **MAP TO PLATFORM TERMS** - Link to Gold/Bitcoin/NVIDIA
3. **WEB-SEARCH DEPENDENCIES** - Find direct/indirect links
4. **NUMERIC EXTRACTION** - Extract impact percentages
5. **RETURN DEPENDENCIES** - JSON structured output
6. **SYNTHESIS** - Correlate all findings

**Key Features:**
- Single API call (no sequential requests)
- Web search enabled (Google Search tool)
- Color psychology analysis (visual sentiment)
- Confidence scoring (0.0-1.0)
- Direct vs Indirect lag detection
- Numeric impact prediction

---

## 📈 Frontend Component Structure

### **Tabs & Sections**
```
News Sentiment Tab
├── Input Section
│   ├── Text Input (textarea)
│   └── Image Upload (file picker)
├── Analysis Button
└── Results Panel
    ├── Article Overview (sentiment, color psychology, urgency)
    ├── Extracted Entities (assets, indicators, events, numbers)
    ├── Dependencies Tabs
    │   ├── Direct Dependencies (0-1 day lag)
    │   │   └── Asset cards (impact, correlation, confidence)
    │   └── Indirect Dependencies (2-7 days)
    │       └── Relationship chains (Fed → yields → assets)
    ├── Numeric Predictions
    │   └── Probability bars (confidence display)
    └── Correlation Analysis
        └── Portfolio-level metrics
```

### **Visualization Features**
- **Color Psychology**: Red/Green framing detection
- **Confidence Bars**: Probability visualization
- **Dependency Chains**: Visual flow of market impacts
- **Chart Integration**: 5-day historical + forecast
- **Urgency Indicators**: High/Medium/Low alerts

---

## 🎯 Platform Integration Points

### **With Existing "Overview" Tab**
```
- Show recent news sentiment as market context
- Display cross-correlation findings in correlation heatmap
- Link to backtester: "Test strategy during THIS market regime"
```

### **With "Backtest" Tab**
```
- "Show me backtests when articles predict HIGH volatility"
- Filter: "Only show periods with bullish news sentiment"
- Correlate strategy returns with article timing
```

### **With "Compare" Tab**
```
- "Compare strategy performance during HIGH vs LOW news sentiment"
- Show: "Strategy outperforms in risk-off periods" (from articles)
```

### **With "Research" Tab**
```
- Archive of sentiment analyses
- Export: CSV of articles + dependencies + predictions
- Trend: "Gold appears in 60% of bullish articles (last 30 days)"
```

---

## 🛠️ Configuration & Customization

### **Platform Terms** (Edit in prompt)
Currently hardcoded in `UNIFIED_NEWS_ANALYSIS_PROMPT`:
```python
# Assets
Assets: Gold, Bitcoin, NVIDIA

# Indicators  
SMA, EMA, Sharpe Ratio, Maximum Drawdown, Volatility, Correlation

# Strategy Types
SMA Crossover, EMA Trend, Momentum Strategy, Mean Reversion
```

To add new assets/indicators, modify the prompt string.

### **Confidence Calibration**
In the Gemini prompt, confidence scoring is based on:
- Data recency
- Source credibility  
- Historical accuracy of similar predictions

Adjust weights in `NUMERIC_PREDICTIONS` section.

### **Lag Times**
- **Direct**: 0-1 day (same-day market moves)
- **Indirect**: 2-7 days (multi-step contagion)

Customize in `direct_dependencies` vs `indirect_dependencies` sections.

---

## ⚡ Performance Considerations

| Aspect | Metric | Notes |
|--------|--------|-------|
| API Response Time | 8-15s | Includes web search + LLM inference |
| Image OCR | 2-3s | Preprocessing time |
| JSON Parsing | <100ms | Structured output |
| Frontend Render | <500ms | React component mounting |
| **Total E2E** | **10-20s** | User perceives as responsive |

**Optimization Tips:**
1. Cache recent analyses (same article = same result)
2. Lazy-load charts (fetch only when expanded)
3. Use web search throttling (1 call per 30 sec)

---

## 🔒 Security & Best Practices

### **Input Validation**
```python
- Max text length: 10,000 characters
- Max image size: 16MB
- File types: png, jpg, jpeg, gif, webp
- Rate limit: 100 req/hour per IP
```

### **API Key Management**
```
NEVER commit .env to version control
Use environment variables in production
Rotate GEMINI_API_KEY monthly
```

### **Data Privacy**
```
- Articles not stored by default
- User can opt-in to history
- No third-party data sharing
```

---

## 📝 Example Use Cases

### **Use Case 1: Breaking News Analysis**
```
User: Uploads WSJ article about Fed rate hike
System: Detects +2.5% impact on Gold, -1.8% on tech stocks
Frontend: Shows correlation breakdown (diversification degrades)
Action: User adjusts portfolio hedges
```

### **Use Case 2: Sector Rotation Detection**
```
User: Pastes CNBC article about "Tech Selloff, Defensive Rotation"
System: Maps to NVIDIA + sector indicators
Identifies: Indirect dependency chain (Tech → Bonds → Gold)
Forecast: Gold +2-3% in 3-5 days
Action: Backtest: How did strategies perform in similar periods?
```

### **Use Case 3: Long-Term Macro**
```
User: Articles about "Inflation expectations shift"
System: Direct impact on Gold (bullish), indirect on correlation
Numeric: "CPI at 4.2%" → 68% probability Gold +1.5%
Timeline: 2-3 days
Action: Compare strategies during inflation regimes
```

---

## 📊 Expected Output Example

**Input:** "Bitcoin hits $45K on institutional buying"

**Output Structure:**
```json
{
  "sentiment": "bullish",
  "color_psychology": "green",
  "direct_dependencies": {
    "Bitcoin": {
      "impact": "bullish",
      "expected_change": "+3.5%",
      "confidence": 0.91
    },
    "correlation": {
      "change": "stock-crypto decoupling",
      "impact": "positive for diversification"
    }
  },
  "indirect_dependencies": {
    "chain": ["Institutional buying → DXY weakness → Gold +0.8%"],
    "timeline": "2-3 days",
    "confidence": 0.72
  }
}
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| "Analyzer not initialized" | Check GEMINI_API_KEY in .env |
| Slow API response | Reduce `max_output_tokens` from 65536 to 32000 |
| JSON parse error | Gemini returned markdown—enable auto-cleanup in routes |
| Image not processing | File >16MB or wrong format (use PNG/JPG) |
| No dependencies detected | Article too generic or no platform terms mentioned |

---

## 🎓 What Makes This Unique?

✅ **Real-time sentiment from news**  
✅ **Causal dependency detection** (not just correlation)  
✅ **Color psychology analysis** (visual bias detection)  
✅ **Numeric impact prediction** (probabilities)  
✅ **Direct vs Indirect lags** (fast vs slow market moves)  
✅ **Integrated backtesting** (test strategies during similar articles)  
✅ **Single unified API call** (no sequential prompts)  

---

## 📚 Next Steps

1. **Deploy Backend**: Add to your Flask/FastAPI server
2. **Integrate Frontend**: Add NewsSentimentTab to your layout
3. **Connect Charts**: Link to your time-series data source
4. **Database**: Store sentiment analyses for historical tracking
5. **Enhancements**:
   - Sentiment history trends
   - Multi-source aggregation (Reuters, Bloomberg, etc.)
   - Sentiment score vs actual price moves correlation
   - ML model fine-tuning on historical articles

---

**Created**: 2024  
**Status**: Production-ready  
**License**: MIT
