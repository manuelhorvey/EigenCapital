from dataclasses import dataclass


@dataclass
class RegimeRow:
    P_trend: float
    P_range: float
    P_volatile: float
    regime_label: str
