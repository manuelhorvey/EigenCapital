"""Macro narrative features — weekly LLM-driven macro context overlay.

Fetches FXStreet "Week ahead" articles, sends to Claude API for structured
JSON extraction, and produces narrative overlays (geopolitical risk, central
bank bias, risk-on/off regime). Applied weekly (Monday before noon ET) with
human confirm step.

Governance effects:
    geopol_risk_score > 0.7   → SL widened by 10%
    overall_regime == risk_off → position size reduced by 20%
    confidence < 0.6          → no governance applied
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime

logger = logging.getLogger("eigencapital.macro_narrative")


@dataclass
class MacroNarrativeFeatures:
    week_start: str
    usd_strength_narrative: float
    geopol_risk_score: float
    fed_hawkishness: float
    rbnz_hawkishness: float
    rba_hawkishness: float
    boj_intervention_risk: float
    energy_crisis_pressure: float
    usd_bias: str
    nzd_bias: str
    aud_bias: str
    jpy_bias: str
    cad_bias: str
    eur_bias: str
    key_events: list[str]
    overall_regime: str
    confidence: float
    narrative_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_feature_vector(self) -> dict[str, float]:
        bias_map = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
        return {
            "usd_strength_narr": self.usd_strength_narrative,
            "geopol_risk": self.geopol_risk_score,
            "fed_hawk": self.fed_hawkishness,
            "rbnz_hawk": self.rbnz_hawkishness,
            "rba_hawk": self.rba_hawkishness,
            "boj_intervene_risk": self.boj_intervention_risk,
            "energy_pressure": self.energy_crisis_pressure,
            "usd_bias_num": bias_map.get(self.usd_bias, 0.0),
            "nzd_bias_num": bias_map.get(self.nzd_bias, 0.0),
            "aud_bias_num": bias_map.get(self.aud_bias, 0.0),
            "jpy_bias_num": bias_map.get(self.jpy_bias, 0.0),
            "cad_bias_num": bias_map.get(self.cad_bias, 0.0),
            "eur_bias_num": bias_map.get(self.eur_bias, 0.0),
            "regime_risk_on": 1.0 if self.overall_regime == "risk_on" else 0.0,
            "regime_geopol": 1.0 if self.overall_regime == "geopol_tension" else 0.0,
        }


def narrative_governance_scalars(
    features: MacroNarrativeFeatures,
    geopol_sl_widen_pct: float = 10.0,
    risk_off_size_reduce_pct: float = 20.0,
    min_confidence: float = 0.6,
    stale: bool = False,
) -> dict:
    if stale or features.confidence < min_confidence:
        return {"sl_mult": 1.0, "size_scalar": 1.0}
    sl_mult = 1.0
    size_scalar = 1.0
    if features.geopol_risk_score > 0.7:
        sl_mult = 1.0 + geopol_sl_widen_pct / 100.0
    if features.overall_regime == "risk_off":
        size_scalar = 1.0 - risk_off_size_reduce_pct / 100.0
    return {"sl_mult": sl_mult, "size_scalar": size_scalar}


def neutral_narrative(week_start: str | None = None) -> MacroNarrativeFeatures:
    return MacroNarrativeFeatures(
        week_start=week_start or datetime.now().strftime("%Y-%m-%d"),
        usd_strength_narrative=0.5,
        geopol_risk_score=0.3,
        fed_hawkishness=0.5,
        rbnz_hawkishness=0.5,
        rba_hawkishness=0.5,
        boj_intervention_risk=0.3,
        energy_crisis_pressure=0.3,
        usd_bias="neutral",
        nzd_bias="neutral",
        aud_bias="neutral",
        jpy_bias="neutral",
        cad_bias="neutral",
        eur_bias="neutral",
        key_events=[],
        overall_regime="data_driven",
        confidence=0.5,
    )


def load_narrative_json(path: str) -> MacroNarrativeFeatures:
    with open(path) as f:
        data = json.load(f)
    return MacroNarrativeFeatures(**data)


def save_narrative_json(path: str, features: MacroNarrativeFeatures) -> None:
    with open(path, "w") as f:
        json.dump(features.to_dict(), f, indent=2, default=str)
