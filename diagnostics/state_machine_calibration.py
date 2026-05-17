import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, Tuple, Optional

from diagnostics.model_validity_timeline import run_timeline, assemble_manifold


class StateMachineCalibration:
    """
    Diagnostic tool for calibrating state machine responsiveness vs stability.
    
    Identifies over-stabilization and provides adaptive parameter recommendations.
    """
    
    def __init__(self, validity_df: pd.DataFrame):
        """
        Args:
            validity_df: DataFrame with validity scores over time
        """
        self.validity_df = validity_df
        self.validity = validity_df["validity"].values
        self.smoothed_validity = validity_df.get("smoothed_validity", self.validity)
        
    def green_reachability_audit(
        self,
        green_entry_threshold: float = 0.70,
        percentile: float = 95.0
    ) -> Dict:
        """
        Audit whether GREEN state is structurally reachable under current distribution.
        
        Args:
            green_entry_threshold: Threshold for entering GREEN
            percentile: Percentile to check (default 95th)
        
        Returns:
            Dictionary with reachability metrics
        """
        validity_p95 = np.percentile(self.validity, percentile)
        smoothed_p95 = np.percentile(self.smoothed_validity, percentile)
        
        raw_reachable = validity_p95 >= green_entry_threshold
        smoothed_reachable = smoothed_p95 >= green_entry_threshold
        
        # Calculate how far from threshold
        raw_gap = green_entry_threshold - validity_p95
        smoothed_gap = green_entry_threshold - smoothed_p95
        
        # Distribution statistics
        validity_mean = self.validity.mean()
        validity_std = self.validity.std()
        validity_range = self.validity.max() - self.validity.min()
        
        return {
            "green_entry_threshold": green_entry_threshold,
            "percentile": percentile,
            "raw_validity_p95": validity_p95,
            "smoothed_validity_p95": smoothed_p95,
            "raw_reachable": raw_reachable,
            "smoothed_reachable": smoothed_reachable,
            "raw_gap_from_threshold": raw_gap,
            "smoothed_gap_from_threshold": smoothed_gap,
            "validity_mean": validity_mean,
            "validity_std": validity_std,
            "validity_range": validity_range,
            "recommendation": self._reachability_recommendation(
                raw_reachable, smoothed_reachable, raw_gap, smoothed_gap
            )
        }
    
    def _reachability_recommendation(
        self,
        raw_reachable: bool,
        smoothed_reachable: bool,
        raw_gap: float,
        smoothed_gap: float
    ) -> str:
        """Generate recommendation based on reachability analysis."""
        if not raw_reachable:
            return "CRITICAL: GREEN unreachable even with raw validity. System lacks signal quality for GREEN state."
        
        if raw_reachable and not smoothed_reachable:
            gap_magnitude = abs(smoothed_gap)
            if gap_magnitude < 0.05:
                return "MODERATE: GREEN reachable raw but blocked by smoothing. Reduce inertia slightly."
            elif gap_magnitude < 0.10:
                return "SIGNIFICANT: Smoothing is preventing GREEN access. Reduce inertia or lower threshold."
            else:
                return "SEVERE: Strong smoothing preventing GREEN. Substantial inertia reduction needed."
        
        if raw_reachable and smoothed_reachable:
            return "HEALTHY: GREEN reachable under both raw and smoothed validity."
        
        return "UNKNOWN: Unable to determine reachability status."
    
    def smoothing_impact_analysis(
        self,
        alpha: float = 0.7,
        beta: float = 0.3
    ) -> Dict:
        """
        Analyze the impact of smoothing strength on signal preservation.
        
        Args:
            alpha: Weight on current validity
            beta: Weight on previous validity
        
        Returns:
            Dictionary with smoothing impact metrics
        """
        # Compute smoothed series with given parameters
        smoothed = np.zeros_like(self.validity)
        smoothed[0] = self.validity[0]
        for i in range(1, len(self.validity)):
            smoothed[i] = alpha * self.validity[i] + beta * smoothed[i-1]
        
        # Calculate signal preservation metrics
        raw_std = self.validity.std()
        smoothed_std = smoothed.std()
        std_ratio = smoothed_std / raw_std if raw_std > 0 else 0
        
        # Phase lag (cross-correlation)
        max_lag = min(10, len(self.validity) // 4)
        correlations = []
        for lag in range(max_lag + 1):
            if lag < len(smoothed) - lag:
                corr = np.corrcoef(
                    self.validity[:-lag] if lag > 0 else self.validity,
                    smoothed[lag:] if lag > 0 else smoothed
                )[0, 1]
                correlations.append(corr)
        
        optimal_lag = np.argmax(correlations) if correlations else 0
        max_correlation = correlations[optimal_lag] if correlations else 0
        
        # Signal-to-noise degradation
        signal_power = np.var(self.validity)
        smoothed_signal_power = np.var(smoothed)
        snr_ratio = smoothed_signal_power / signal_power if signal_power > 0 else 0
        
        return {
            "alpha": alpha,
            "beta": beta,
            "raw_std": raw_std,
            "smoothed_std": smoothed_std,
            "std_ratio": std_ratio,
            "signal_preservation": std_ratio,
            "optimal_lag": optimal_lag,
            "max_correlation": max_correlation,
            "snr_ratio": snr_ratio,
            "recommendation": self._smoothing_recommendation(std_ratio, max_correlation)
        }
    
    def _smoothing_recommendation(
        self,
        std_ratio: float,
        max_correlation: float
    ) -> str:
        """Generate recommendation based on smoothing impact."""
        if std_ratio < 0.5:
            return "EXCESSIVE: Smoothing destroys >50% of signal variance. Reduce inertia significantly."
        elif std_ratio < 0.7:
            return "HIGH: Smoothing reduces 30-50% of signal variance. Consider reducing inertia."
        elif std_ratio < 0.85:
            return "MODERATE: Acceptable signal preservation with some noise reduction."
        elif max_correlation < 0.9:
            return "LOW: Good preservation but check phase lag."
        else:
            return "OPTIMAL: Strong signal preservation with minimal distortion."
    
    def adaptive_smoothing_calibration(
        self,
        target_preservation: float = 0.80,
        volatility_window: int = 10
    ) -> Dict:
        """
        Calibrate adaptive smoothing parameters based on local volatility.
        
        Args:
            target_preservation: Target signal preservation ratio (0-1)
            volatility_window: Window for local volatility calculation
        
        Returns:
            Dictionary with adaptive parameters
        """
        # Calculate rolling volatility
        rolling_std = pd.Series(self.validity).rolling(
            window=volatility_window, min_periods=1
        ).std().fillna(self.validity.std())
        
        # Normalize volatility
        vol_percentiles = rolling_std.rank(pct=True)
        
        # Adaptive alpha: higher volatility → more smoothing (lower alpha)
        # Map volatility percentile to alpha range [0.6, 0.95]
        adaptive_alpha = 0.95 - 0.35 * vol_percentiles
        adaptive_beta = 1.0 - adaptive_alpha
        
        # Apply adaptive smoothing
        smoothed_adaptive = np.zeros_like(self.validity)
        smoothed_adaptive[0] = self.validity[0]
        for i in range(1, len(self.validity)):
            smoothed_adaptive[i] = (
                adaptive_alpha.iloc[i] * self.validity[i] +
                adaptive_beta.iloc[i] * smoothed_adaptive[i-1]
            )
        
        # Check if target preservation achieved
        adaptive_std = smoothed_adaptive.std()
        raw_std = self.validity.std()
        actual_preservation = adaptive_std / raw_std if raw_std > 0 else 0
        
        return {
            "target_preservation": target_preservation,
            "actual_preservation": actual_preservation,
            "volatility_window": volatility_window,
            "adaptive_alpha_range": (adaptive_alpha.min(), adaptive_alpha.max()),
            "adaptive_beta_range": (adaptive_beta.min(), adaptive_beta.max()),
            "mean_adaptive_alpha": adaptive_alpha.mean(),
            "recommendation": self._adaptive_recommendation(
                target_preservation, actual_preservation
            )
        }
    
    def _adaptive_recommendation(
        self,
        target: float,
        actual: float
    ) -> str:
        """Generate recommendation for adaptive smoothing."""
        if actual < target - 0.1:
            return "UNDER-PRESERVING: Adaptive smoothing too aggressive. Increase alpha range."
        elif actual > target + 0.1:
            return "OVER-PRESERVING: Adaptive smoothing too weak. Decrease alpha range."
        else:
            return "WELL-CALIBRATED: Adaptive smoothing achieves target preservation."
    
    def dynamic_threshold_analysis(
        self,
        base_green_entry: float = 0.70,
        base_green_exit: float = 0.60,
        base_yellow_entry: float = 0.45,
        base_yellow_exit: float = 0.40,
        volatility_scaling: float = 0.1
    ) -> Dict:
        """
        Analyze dynamic threshold scaling based on validity volatility.
        
        Args:
            base_green_entry: Base GREEN entry threshold
            base_green_exit: Base GREEN exit threshold
            base_yellow_entry: Base YELLOW entry threshold
            base_yellow_exit: Base YELLOW exit threshold
            volatility_scaling: Scaling factor for volatility adjustment
        
        Returns:
            Dictionary with dynamic threshold analysis
        """
        # Calculate rolling volatility
        rolling_std = pd.Series(self.validity).rolling(
            window=10, min_periods=1
        ).std().fillna(self.validity.std())
        
        # Normalize to [0, 1]
        vol_normalized = (rolling_std - rolling_std.min()) / (
            rolling_std.max() - rolling_std.min() + 1e-12
        )
        
        # Dynamic thresholds: higher volatility → wider bands
        dynamic_green_entry = base_green_entry + volatility_scaling * vol_normalized
        dynamic_green_exit = base_green_exit - volatility_scaling * vol_normalized
        dynamic_yellow_entry = base_yellow_entry + volatility_scaling * vol_normalized
        dynamic_yellow_exit = base_yellow_exit - volatility_scaling * vol_normalized
        
        # Calculate band widths
        green_band = dynamic_green_entry - dynamic_green_exit
        yellow_band = dynamic_yellow_entry - dynamic_yellow_exit
        
        return {
            "base_green_entry": base_green_entry,
            "base_green_exit": base_green_exit,
            "dynamic_green_entry_range": (dynamic_green_entry.min(), dynamic_green_entry.max()),
            "dynamic_green_exit_range": (dynamic_green_exit.min(), dynamic_green_exit.max()),
            "green_band_width_range": (green_band.min(), green_band.max()),
            "yellow_band_width_range": (yellow_band.min(), yellow_band.max()),
            "volatility_scaling": volatility_scaling,
            "recommendation": self._dynamic_threshold_recommendation(green_band.mean())
        }
    
    def _dynamic_threshold_recommendation(self, mean_band_width: float) -> str:
        """Generate recommendation for dynamic thresholds."""
        if mean_band_width < 0.05:
            return "TOO TIGHT: Bands too narrow, may cause flickering. Increase volatility scaling."
        elif mean_band_width < 0.10:
            return "NARROW: Bands narrow but acceptable. Consider slight increase."
        elif mean_band_width < 0.20:
            return "OPTIMAL: Bands provide good hysteresis without excessive inertia."
        else:
            return "TOO WIDE: Bands too wide, may cause saturation. Decrease volatility scaling."
    
    def comprehensive_calibration_report(
        self,
        green_entry_threshold: float = 0.70
    ) -> Dict:
        """
        Generate comprehensive calibration report with all analyses.
        
        Args:
            green_entry_threshold: GREEN entry threshold to audit
        
        Returns:
            Dictionary with all calibration analyses
        """
        return {
            "green_reachability": self.green_reachability_audit(green_entry_threshold),
            "smoothing_impact": self.smoothing_impact_analysis(alpha=0.7, beta=0.3),
            "adaptive_smoothing": self.adaptive_smoothing_calibration(),
            "dynamic_thresholds": self.dynamic_threshold_analysis(),
            "summary": self._generate_summary()
        }
    
    def _generate_summary(self) -> Dict:
        """Generate summary of calibration findings."""
        reachability = self.green_reachability_audit()
        smoothing = self.smoothing_impact_analysis()
        
        return {
            "primary_issue": self._identify_primary_issue(reachability, smoothing),
            "priority_fixes": self._priority_fixes(reachability, smoothing),
            "estimated_responsiveness": self._estimate_responsiveness(reachability, smoothing)
        }
    
    def _identify_primary_issue(
        self,
        reachability: Dict,
        smoothing: Dict
    ) -> str:
        """Identify primary calibration issue."""
        if not reachability["raw_reachable"]:
            return "SIGNAL_QUALITY: Raw validity insufficient for GREEN state."
        elif reachability["raw_reachable"] and not reachability["smoothed_reachable"]:
            return "OVER_SMOOTHING: Inertia preventing state transitions."
        elif smoothing["std_ratio"] < 0.6:
            return "EXCESSIVE_DAMPENING: Smoothing destroys signal variance."
        else:
            return "WELL_BALANCED: System parameters appear reasonable."
    
    def _priority_fixes(
        self,
        reachability: Dict,
        smoothing: Dict
    ) -> list:
        """Generate list of priority fixes."""
        fixes = []
        
        if not reachability["smoothed_reachable"] and reachability["raw_reachable"]:
            fixes.append({
                "priority": "HIGH",
                "action": "Reduce smoothing inertia (increase alpha to 0.85+)",
                "reason": "GREEN reachable raw but blocked by smoothing"
            })
        
        if smoothing["std_ratio"] < 0.7:
            fixes.append({
                "priority": "HIGH",
                "action": "Implement adaptive smoothing based on volatility",
                "reason": f"Signal preservation only {smoothing['std_ratio']:.2%}"
            })
        
        if reachability["smoothed_gap_from_threshold"] > 0.05:
            fixes.append({
                "priority": "MEDIUM",
                "action": "Lower GREEN entry threshold or implement dynamic thresholds",
                "reason": f"Smoothed validity {reachability['smoothed_gap_from_threshold']:.3f} below threshold"
            })
        
        if not fixes:
            fixes.append({
                "priority": "LOW",
                "action": "Monitor system behavior",
                "reason": "No critical issues detected"
            })
        
        return fixes
    
    def _estimate_responsiveness(
        self,
        reachability: Dict,
        smoothing: Dict
    ) -> str:
        """Estimate current system responsiveness."""
        if not reachability["smoothed_reachable"]:
            return "LOW: System cannot reach GREEN state"
        elif smoothing["std_ratio"] < 0.6:
            return "LOW-TO-MODERATE: Excessive dampening limits responsiveness"
        elif smoothing["std_ratio"] < 0.8:
            return "MODERATE: Balanced stability and responsiveness"
        else:
            return "HIGH: Strong signal preservation enables responsiveness"


def run_calibration_audit():
    """
    Run comprehensive calibration audit on current timeline data.
    """
    print("=" * 60)
    print("STATE MACHINE CALIBRATION AUDIT")
    print("=" * 60)
    
    # Get timeline data
    timeline = run_timeline(use_state_machine=True)
    
    # Run calibration
    calibrator = StateMachineCalibration(timeline)
    report = calibrator.comprehensive_calibration_report()
    
    # Print GREEN reachability audit
    print("\n" + "=" * 60)
    print("GREEN REACHABILITY AUDIT")
    print("=" * 60)
    reach = report["green_reachability"]
    print(f"GREEN entry threshold: {reach['green_entry_threshold']:.3f}")
    print(f"95th percentile raw validity: {reach['raw_validity_p95']:.4f}")
    print(f"95th percentile smoothed validity: {reach['smoothed_validity_p95']:.4f}")
    print(f"Raw reachable: {reach['raw_reachable']}")
    print(f"Smoothed reachable: {reach['smoothed_reachable']}")
    print(f"Raw gap from threshold: {reach['raw_gap_from_threshold']:.4f}")
    print(f"Smoothed gap from threshold: {reach['smoothed_gap_from_threshold']:.4f}")
    print(f"\nValidity statistics:")
    print(f"  Mean: {reach['validity_mean']:.4f}")
    print(f"  Std: {reach['validity_std']:.4f}")
    print(f"  Range: {reach['validity_range']:.4f}")
    print(f"\nRecommendation: {reach['recommendation']}")
    
    # Print smoothing impact
    print("\n" + "=" * 60)
    print("SMOOTHING IMPACT ANALYSIS")
    print("=" * 60)
    smooth = report["smoothing_impact"]
    print(f"Current parameters: alpha={smooth['alpha']:.2f}, beta={smooth['beta']:.2f}")
    print(f"Raw validity std: {smooth['raw_std']:.4f}")
    print(f"Smoothed validity std: {smooth['smoothed_std']:.4f}")
    print(f"Signal preservation ratio: {smooth['std_ratio']:.4f}")
    print(f"Optimal lag: {smooth['optimal_lag']}")
    print(f"Max correlation: {smooth['max_correlation']:.4f}")
    print(f"SNR ratio: {smooth['snr_ratio']:.4f}")
    print(f"\nRecommendation: {smooth['recommendation']}")
    
    # Print adaptive smoothing
    print("\n" + "=" * 60)
    print("ADAPTIVE SMOOTHING CALIBRATION")
    print("=" * 60)
    adaptive = report["adaptive_smoothing"]
    print(f"Target preservation: {adaptive['target_preservation']:.2%}")
    print(f"Actual preservation: {adaptive['actual_preservation']:.2%}")
    print(f"Adaptive alpha range: [{adaptive['adaptive_alpha_range'][0]:.3f}, {adaptive['adaptive_alpha_range'][1]:.3f}]")
    print(f"Mean adaptive alpha: {adaptive['mean_adaptive_alpha']:.3f}")
    print(f"\nRecommendation: {adaptive['recommendation']}")
    
    # Print dynamic thresholds
    print("\n" + "=" * 60)
    print("DYNAMIC THRESHOLD ANALYSIS")
    print("=" * 60)
    dynamic = report["dynamic_thresholds"]
    print(f"Base GREEN entry: {dynamic['base_green_entry']:.3f}")
    print(f"Dynamic GREEN entry range: [{dynamic['dynamic_green_entry_range'][0]:.3f}, {dynamic['dynamic_green_entry_range'][1]:.3f}]")
    print(f"GREEN band width range: [{dynamic['green_band_width_range'][0]:.3f}, {dynamic['green_band_width_range'][1]:.3f}]")
    print(f"Volatility scaling: {dynamic['volatility_scaling']:.3f}")
    print(f"\nRecommendation: {dynamic['recommendation']}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("CALIBRATION SUMMARY")
    print("=" * 60)
    summary = report["summary"]
    print(f"Primary issue: {summary['primary_issue']}")
    print(f"\nPriority fixes:")
    for i, fix in enumerate(summary["priority_fixes"], 1):
        print(f"  {i}. [{fix['priority']}] {fix['action']}")
        print(f"     Reason: {fix['reason']}")
    print(f"\nEstimated responsiveness: {summary['estimated_responsiveness']}")
    
    print("\n" + "=" * 60)
    
    return report


if __name__ == "__main__":
    run_calibration_audit()
