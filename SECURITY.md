# Security Policy

## Overview

EigenCapital is a quantitative trading platform that handles live capital through a MetaTrader 5 broker connection. Security issues can directly result in financial loss.

## Scope

The following are in scope for security reports:

- **Broker connection security**: MT5 bridge authentication, session management, credential handling
- **Order execution safety**: Unauthorized order submission, order manipulation, bypass of risk gates
- **Strategy integrity**: R4 signal tampering, fingerprint bypass, config drift exploitation
- **Data integrity**: Audit trail manipulation, evidence tampering, state corruption
- **Access control**: Unauthorized access to trading processes, configuration files, or credentials
- **Dependency vulnerabilities**: Known CVEs in dependencies that could affect the trading system

## Out of Scope

- Theoretical trading strategy weaknesses (these are research questions, not security issues)
- Documentation inaccuracies
- UI/cosmetic issues
- Issues requiring physical access to the trading machine

## Reporting

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email: ameymanuel@gmail.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact (especially financial impact)
- Suggested fix (if any)

## Response Timeline

| Action | Timeline |
|--------|----------|
| Acknowledgment | 24 hours |
| Initial assessment | 72 hours |
| Fix or mitigation | 7 days for critical, 30 days for others |
| Public disclosure | After fix is deployed and verified |

## Critical Security Controls

The following controls are designed to prevent the most dangerous failure modes:

| Control | Implementation | Fail Mode |
|---------|---------------|-----------|
| Fingerprint verification | Startup + every cycle | HALT trading |
| Risk gate enforcement | 7 independent gates | BLOCK new entries |
| Catastrophic SL | 2×ATR14 or 1% floor | Automatic position closure |
| Reconciliation | 8 broker-internal checks | HALT on mismatch |
| Audit trail | Append-only JSONL with fsync | Crash-resistant |
| Order timeout | 30s via ThreadPoolExecutor | Prevent hung sessions |
| Force-regime block | `--force-regime` blocked in `--loop` | Exit with error |

## Credential Handling

- Broker credentials are NOT stored in the repository
- Use environment variables or `.env` files (gitignored)
- `.env.example` provides the template — never commit actual values
- MT5 bridge runs locally on port 8001 — not exposed to network
- Telegram webhook tokens loaded from environment variables only

## Dependencies

Run `pip audit` periodically to check for known vulnerabilities in dependencies.

Key dependencies:
- `mt5linux` — MT5 bridge for Linux
- `numpy`, `pandas` — Research/strategy computation
- `pytest`, `ruff`, `mypy` — Development tooling only
