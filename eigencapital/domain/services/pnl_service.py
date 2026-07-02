from __future__ import annotations

from abc import ABC, abstractmethod


class PnLService(ABC):
    @abstractmethod
    def compute_daily(
        self,
        current_value: float,
        direction: int,
        ret: float,
        position_size_fraction: float,
        pos_size: float,
    ) -> float: ...


class DefaultPnLService(PnLService):
    def compute_daily(
        self,
        current_value: float,
        direction: int,
        ret: float,
        position_size_fraction: float,
        pos_size: float,
    ) -> float:
        return current_value * direction * ret * position_size_fraction * pos_size
