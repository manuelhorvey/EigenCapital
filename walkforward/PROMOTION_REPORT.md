# Promotion Report — Walk-Forward Screening

*Generated: 2026-05-28 12:14*

## 1. Executive Summary

- **Total tickers screened:** 30
- **GREEN (promote):** 3
- **YELLOW (watch):**  11
- **RED (skip):**      16

**Top 3 tickers:**
  1. **BTCUSD** — score 80.9/100, IC 0.2264, hit rate 48.3%, 4/5 positive folds
  2. **EURGBP** — score 69.0/100, IC 0.1104, hit rate 41.5%, 4/5 positive folds
  3. **GC** — score 66.7/100, IC 0.1270, hit rate 40.4%, 4/5 positive folds

## 2. GREEN — Promote to Live Dashboard

### BTCUSD

**Score:** 80.9/100  |  **IC:** 0.2264  |  **Hit Rate:** 48.3%  |  **Flat Rate:** 26.8%
**Positive IC folds:** 4/5  |  **Long:** 60.8%  |  **Short:** 12.4%
**Recommendation:** PROMOTE — consistent edge across 4/5 folds, bidirectional signal (long 60.8%, short 12.4%)

### EURGBP

**Score:** 69.0/100  |  **IC:** 0.1104  |  **Hit Rate:** 41.5%  |  **Flat Rate:** 47.4%
**Positive IC folds:** 4/5  |  **Long:** 34.1%  |  **Short:** 18.6%
**Recommendation:** PROMOTE — consistent edge across 4/5 folds, bidirectional signal (long 34.1%, short 18.6%)

### GC

**Score:** 66.7/100  |  **IC:** 0.1270  |  **Hit Rate:** 40.4%  |  **Flat Rate:** 37.9%
**Positive IC folds:** 4/5  |  **Long:** 42.3%  |  **Short:** 19.9%
**Recommendation:** PROMOTE — consistent edge across 4/5 folds, bidirectional signal (long 42.3%, short 19.9%)

## 3. YELLOW — Watch List

### NZDCHF

**Score:** 70.0/100  |  **IC:** 0.1503  |  **Hit Rate:** 38.4%  |  **Flat Rate:** 45.9%
**Positive IC folds:** 5/5
**Note:** hit rate 38.4% below 40%

### AUDCAD

**Score:** 61.0/100  |  **IC:** 0.0964  |  **Hit Rate:** 25.4%  |  **Flat Rate:** 39.7%
**Positive IC folds:** 4/5
**Note:** hit rate 25.4% below 40%

### EURJPY

**Score:** 61.0/100  |  **IC:** 0.0974  |  **Hit Rate:** 38.8%  |  **Flat Rate:** 54.3%
**Positive IC folds:** 3/5
**Note:** hit rate 38.8% below 40%

### EURCAD

**Score:** 58.3/100  |  **IC:** 0.0774  |  **Hit Rate:** 42.7%  |  **Flat Rate:** 47.5%
**Positive IC folds:** 3/5
**Note:** multiple criteria missed

### CHFJPY

**Score:** 56.5/100  |  **IC:** 0.0763  |  **Hit Rate:** 36.7%  |  **Flat Rate:** 32.6%
**Positive IC folds:** 4/5
**Note:** hit rate 36.7% below 40%

### AUDCHF

**Score:** 54.6/100  |  **IC:** 0.0814  |  **Hit Rate:** 38.1%  |  **Flat Rate:** 55.9%
**Positive IC folds:** 3/5
**Note:** hit rate 38.1% below 40%

### USDJPY

**Score:** 54.3/100  |  **IC:** 0.0808  |  **Hit Rate:** 36.4%  |  **Flat Rate:** 44.8%
**Positive IC folds:** 3/5
**Note:** hit rate 36.4% below 40%

### USDCHF

**Score:** 50.9/100  |  **IC:** 0.0623  |  **Hit Rate:** 38.9%  |  **Flat Rate:** 43.4%
**Positive IC folds:** 4/5
**Note:** hit rate 38.9% below 40%

### USDCAD

**Score:** 46.4/100  |  **IC:** 0.0610  |  **Hit Rate:** 35.6%  |  **Flat Rate:** 48.3%
**Positive IC folds:** 3/5
**Note:** hit rate 35.6% below 40%

### CADJPY

**Score:** 46.2/100  |  **IC:** 0.0504  |  **Hit Rate:** 38.2%  |  **Flat Rate:** 43.4%
**Positive IC folds:** 4/5
**Note:** hit rate 38.2% below 40%

### GBPCHF

**Score:** 45.5/100  |  **IC:** 0.0314  |  **Hit Rate:** 46.2%  |  **Flat Rate:** 47.6%
**Positive IC folds:** 3/5
**Note:** multiple criteria missed

## 4. RED — Do Not Promote

- **EURUSD** (score 37.8/100, IC 0.0389) — multiple criteria missed
- **GBPAUD** (score 37.5/100, IC 0.0327) — multiple criteria missed
- **EURNZD** (score 35.7/100, IC 0.0266) — IC=0.0266 below 0.03 threshold
- **AUDJPY** (score 33.3/100, IC 0.0281) — hit rate 32.4% <= 40%
- **EURAUD** (score 30.9/100, IC -0.0007) — IC <= 0 (negative edge)
- **CADCHF** (score 24.3/100, IC -0.0012) — IC <= 0 (negative edge)
- **GBPJPY** (score 23.8/100, IC 0.0045) — hit rate 33.7% <= 40%
- **EURCHF** (score 20.6/100, IC -0.0035) — IC <= 0 (negative edge)
- **GBPCAD** (score 17.3/100, IC -0.0000) — IC <= 0 (negative edge)
- **GBPUSD** (score 1.7/100, IC -0.0524) — IC <= 0 (negative edge)
- **NZDJPY** (score -1.3/100, IC -0.0484) — IC <= 0 (negative edge)
- **AUDNZD** (score -5.7/100, IC -0.0593) — IC <= 0 (negative edge)
- **NZDCAD** (score -8.9/100, IC -0.0563) — IC <= 0 (negative edge)
- **AUDUSD** (score -10.1/100, IC -0.0604) — IC <= 0 (negative edge)
- **NZDUSD** (score -12.8/100, IC -0.0769) — IC <= 0 (negative edge)
- **GBPNZD** (score -18.4/100, IC -0.0803) — IC <= 0 (negative edge)

## 5. Paper Trading Configuration Block

Paste this into `configs/paper_trading.yaml`:

```yaml
assets:
  - ticker: BTC-USD
    slug: BTCUSD
    allocation: 0.333   # equal weight across 3 GREEN assets
  - ticker: EURGBP=X
    slug: EURGBP
    allocation: 0.333   # equal weight across 3 GREEN assets
  - ticker: GC=F
    slug: GC
    allocation: 0.333   # equal weight across 3 GREEN assets
```
