# EigenCapital — Deployment Reproducibility Report

## Fresh Machine Deployment

### Linux

```bash
# 1. Install Python 3.14+
python3 --version  # must be >= 3.14

# 2. Clone repository
git clone <repo-url> && cd EigenCapital

# 3. Install dependencies
pip install -e .

# 4. Configure secrets
cp .env.example .env
# Edit .env with MT5 credentials, Telegram tokens

# 5. Verify environment
python3 -c "from eigencapital.config import load_config; load_config('production')"

# 6. Verify fingerprints
python3 -c "from eigencapital.fidelity.r4_manifest import R4ConfigManifest; print(R4ConfigManifest().compute_identity())"
# Must match: aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb

# 7. Run tests
python3 -m pytest tests/ -q  # 2251+ pass, 5 pre-existing failures

# 8. Start supervised process
python3 scripts/r4_rebalance_loop.py --loop
```

### Windows

```cmd
# 1. Install Python 3.14+
python --version

# 2. Clone repository
git clone <repo-url> && cd EigenCapital

# 3. Install dependencies
pip install -e .

# 4. Configure secrets
copy .env.example .env

# 5. Install MT5 natively (not via Wine)

# 6. Start process
python scripts\r4_rebalance_loop.py --loop
```

## Documented Assumptions

| Assumption | Linux | Windows | Status |
|-----------|-------|---------|--------|
| Python 3.14+ | ✅ | ✅ | Required |
| MT5 access | Wine bridge | Native | Both supported via abstraction |
| Telegram alerts | env vars | env vars | Platform-independent |
| File system | POSIX | NTFS | pathlib used |
| Process signals | SIGINT/SIGTERM | CTRL_C_EVENT | Cross-platform handler |
| Timezone | UTC | UTC | UTC-only in live paths |

## Reproducibility Status

| Dimension | Status |
|-----------|--------|
| Dependencies documented | ✅ pyproject.toml |
| Python version specified | ✅ >=3.14 |
| Configuration single source | ✅ config.toml |
| Secrets external | ✅ env vars |
| Tests reproducible | ✅ 2251+ pass |
| Fingerprints verifiable | ✅ R4 manifest |
| MT5 integration | ⚠️ Requires MT5 installation |
| Windows validation | ⚠️ Not tested in CI |

## Gap

**No lockfile** — dependencies are specified in pyproject.toml but not locked
to exact versions. Two machines with the same pyproject.toml may install
different dependency versions. This is acceptable for development but not for
production reproducibility.

**Recommendation:** Add `pip-compile` or `poetry.lock` for exact dependency pinning.
