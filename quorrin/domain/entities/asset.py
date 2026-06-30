from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssetContract:
    name: str
    ticker: str
    features: tuple[str, ...] = ()
    sl: float = 1.0
    pt: float = 2.5
    vertical_barrier: int = 10

    @classmethod
    def from_dict(cls, data: dict) -> AssetContract:
        return cls(
            name=data["name"],
            ticker=data["ticker"],
            features=tuple(data.get("features", ())),
            sl=float(data.get("sl", 1.0)),
            pt=float(data.get("pt", 2.5)),
            vertical_barrier=int(data.get("vertical_barrier", 10)),
        )


@dataclass
class AssetSpec:
    ticker: str
    name: str
    contract: AssetContract
    allocation: float = 0.0
    sl_mult: float = 1.0
    tp_mult: float = 2.5
    halt_config: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    regime_geometry: dict = field(default_factory=dict)
    initial_capital: float = 0.0
    position_size: float = 0.95
    expected_prob_conf: float = 0.45
    retrain_window: int | None = None
