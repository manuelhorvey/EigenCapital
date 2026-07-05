# Broker Domain — MT5 bridge connection

MT5 broker bridge configuration.

| File | Purpose |
|------|---------|
| `mt5.yaml` | Bridge host (`127.0.0.1`), port (`9879`), and symbol map path

The symbol map at `configs/mt5_symbol_map.yaml` translates EigenCapital ticker
names to MetaTrader5 symbol names. Add or comment out symbols there when
adding/removing assets.

Bridge security: non-loopback hosts require `allow_remote_bridge=True` override
(logs a warning). See `paper_trading/ops/mt5_client.py:_is_loopback()`.
