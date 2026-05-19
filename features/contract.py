from dataclasses import dataclass
from typing import Literal
import pandas as pd


class FeatureMismatchError(ValueError):
    pass


@dataclass(frozen=True)
class FeatureContract:
    ticker: str
    name: str
    label_type: Literal["tb20", "fwd60"]
    label_params: dict
    macro_filters: tuple[str, ...]
    price_mom_windows: tuple[int, ...]
    vs_spy_windows: tuple[int, ...]
    warmup_rows: int = 90
    min_history_days: int = 250

    @property
    def requires_ref(self) -> bool:
        return len(self.vs_spy_windows) > 0

    @property
    def features(self) -> tuple[str, ...]:
        parts = list(self.macro_filters)
        slug = self.name.lower()
        for w in self.price_mom_windows:
            parts.append(f"{slug}_mom_{w}")
        for w in self.vs_spy_windows:
            parts.append(f"{slug}_vs_spy_{w}")
        return tuple(parts)

    def validate_dataframe(self, df: pd.DataFrame) -> None:
        expected = list(self.features)
        actual = list(df.columns[:len(expected)])
        if actual != expected:
            raise FeatureMismatchError(
                f"{self.name}: expected columns {expected}, got {actual}. "
                f"Missing: {set(expected) - set(actual)}. "
                f"Extra: {set(actual) - set(expected)}."
            )

    def validate_model(self, model) -> None:
        try:
            model_feats = model.get_booster().feature_names
        except AttributeError:
            return
        expected = set(self.features)
        actual = set(model_feats)
        if actual != expected:
            raise FeatureMismatchError(
                f"{self.name}: model trained on {model_feats}, "
                f"contract requires {self.features}. "
                f"Missing: {expected - actual}. "
                f"Extra: {actual - expected}."
            )
