import logging

import numpy as np

logger = logging.getLogger("eigencapital.ensemble")


class EnsembleSignal:
    """
    Combines base model and regime-conditional model predictions.

    Both models use binary:logistic and output P(LONG).
    The ensemble blends them with a configurable weight and produces
    signals using the ensemble threshold.

    Ensemble threshold interpretation (binary P(LONG) in [0, 1]):
        P(LONG) > 0.5 + threshold/2  →  LONG
        P(LONG) < 0.5 - threshold/2  →  SHORT
        else                          →  FLAT

    Parameters
    ----------
    base_weight : float
        Weight assigned to the base model (0.0 to 1.0).
        Regime weight = 1 - base_weight.
    ensemble_threshold : float
        Half-width of the neutral band around 0.5 (default 0.15).
        At 0.15: LONG if P(LONG) > 0.575, SHORT if < 0.425.
    """

    def __init__(
        self,
        base_weight: float = 0.6,
        ensemble_threshold: float = 0.15,
    ):
        self.base_weight = base_weight
        self.regime_weight = 1.0 - base_weight
        self.ensemble_threshold = ensemble_threshold

    def combine(
        self,
        base_p_long: np.ndarray,
        regime_p_long: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Blend base and regime P(LONG) into a single signal.

        Parameters
        ----------
        base_p_long : np.ndarray, shape (n, 1) or (n,)
            P(LONG) from the base model.
        regime_p_long : np.ndarray, shape (n, 1) or (n,), optional
            P(LONG) from the regime-conditional model.
            If None, uses base_p_long as-is.

        Returns
        -------
        blended_p_long : np.ndarray, shape (n, 1)
        signals : np.ndarray, shape (n,), int in {-1, 0, 1}
        """
        b = np.asarray(base_p_long).ravel()

        if regime_p_long is not None:
            r = np.asarray(regime_p_long).ravel()
            blended = self.base_weight * b + self.regime_weight * r
        else:
            blended = b

        hi = 0.5 + self.ensemble_threshold / 2.0
        lo = 0.5 - self.ensemble_threshold / 2.0

        signals = np.zeros(len(blended), dtype=int)
        signals[blended > hi] = 1
        signals[blended < lo] = -1

        return blended.reshape(-1, 1), signals

    def combine_and_expand(
        self,
        base_p_long: np.ndarray,
        regime_p_long: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Like combine() but returns 3-column probabilities for pipeline
        compatibility: [P(SHORT), P(NEUTRAL), P(LONG)].

        The signal decision is still made from binary P(LONG) using the
        ensemble neutral band. Directional rows expose the complementary
        short/long probabilities. Neutral-band rows intentionally set both
        directional probabilities to zero so the downstream fixed-threshold
        signal strategy cannot override the ensemble's neutral decision.
        """
        blended, signals = self.combine(base_p_long, regime_p_long)
        p = blended.ravel()
        three_col = np.zeros((len(p), 3), dtype=float)

        long_mask = signals == 1
        short_mask = signals == -1
        neutral_mask = signals == 0

        three_col[long_mask, 0] = 1.0 - p[long_mask]
        three_col[long_mask, 2] = p[long_mask]
        three_col[short_mask, 0] = 1.0 - p[short_mask]
        three_col[short_mask, 2] = p[short_mask]
        three_col[neutral_mask, 1] = 0.5
        return three_col, signals
