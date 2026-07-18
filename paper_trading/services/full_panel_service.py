import logging

logger = logging.getLogger("eigencapital.full_panel_service")


class FullPanelService:
    def __init__(self, engine):
        self.engine = engine

    def build(self):
        import pandas as pd

        from features.data_fetch import fetch_asset_data

        cached = getattr(self.engine, "_full_panel_cache", None)
        if cached is not None and not cached.empty and len(cached.columns) == len(self.engine.assets):
            return cached

        panel_dict = {}
        for aname, aengine in self.engine.assets.items():
            try:
                ticker = getattr(aengine, "ticker", None) or getattr(getattr(aengine, "asset", None), "ticker", None)
                if ticker is None:
                    continue
                aprices, _, _, _, _, _ = fetch_asset_data(aname, ticker)
                if aprices is not None and not aprices.empty:
                    panel_dict[aname] = aprices.iloc[:, 0]
            except (OSError, ValueError, KeyError, RuntimeError, AttributeError):
                continue

        if not panel_dict:
            self.engine._full_panel_cache = None
            return None

        full_panel = pd.DataFrame(panel_dict).ffill().dropna(how="all")
        self.engine._full_panel_cache = full_panel
        return full_panel

    def invalidate(self):
        self.engine._full_panel_cache = None
