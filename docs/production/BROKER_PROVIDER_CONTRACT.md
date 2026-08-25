# EigenCapital — Broker Provider Contract

## Strict TradingProvider Contract

### Interface Requirements

Every method must satisfy behavioral guarantees beyond the type signature:

| Method | Contract | Failure Behavior |
|--------|----------|-----------------|
| `connect()` | Returns True on success, False on failure | Must not leave partial state |
| `disconnect()` | Clean shutdown, no side effects | Must be idempotent |
| `is_connected()` | Reflects actual connection state | Must not return True when disconnected |
| `account_info()` | Returns None if disconnected | Must not cache stale data |
| `positions_get()` | Returns broker-authoritative positions | Must reflect actual open positions |
| `symbol_info()` | Returns None for unknown symbols | Must not invent metadata |
| `symbol_info_tick()` | Returns current bid/ask | Must reflect actual market state |
| `order_send()` | Returns OrderResult with ticket/deal | Must provide unique ticket IDs |
| `emergency_flatten()` | Closes all positions, returns results | Must retry on failure, report partial closes |

### Conformance Tests

| Test | What It Proves |
|------|---------------|
| `test_connect_disconnect_cycle` | Clean lifecycle |
| `test_account_info_when_disconnected` | Fail-closed on disconnected |
| `test_order_send_returns_unique_tickets` | No duplicate tickets |
| `test_emergency_flatten_closes_all` | Complete position closure |
| `test_provider_instantiation` | All abstract methods implemented |

### Provider Implementations

| Provider | Platform | Status |
|----------|----------|--------|
| LinuxMT5Provider | Linux (Wine bridge) | ✅ Implemented |
| WindowsMT5Provider | Windows (native MT5) | ⬜ Stub — requires Windows testing |
| FakeProvider | Test only | ✅ Implemented |

### Critical Invariant

The strategy, risk, and execution layers MUST depend only on `TradingProvider`,
never on platform-specific MT5 modules. This has been verified by:
- `tests/unit/test_trading_provider.py` — 20 contract tests
- `tests/unit/test_security_audit.py` — research/live boundary enforcement

### Remaining Gap

**WindowsMT5Provider** is defined but not yet implemented with actual Windows MT5
integration. This is the primary platform gap. The abstraction exists, but conformance
testing requires actual Windows MT5 environment.
