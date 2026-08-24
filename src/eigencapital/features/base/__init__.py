"""Base feature primitives — the foundational vocabulary.

These are the atomic building blocks for all alpha research:
- returns: simple, log, cumulative, multi-horizon
- volatility: realized, Parkinson, Garman-Klass, ratio
- ranges: ATR, high-low, normalized range
- volume: volume MA, volume ratio, volume-zscore

All features are:
- Deterministic (same inputs → same output)
- Registered in FeatureRegistry
- Computed from available bars only (no look-ahead)
- Versioned and provenance-tracked
"""
