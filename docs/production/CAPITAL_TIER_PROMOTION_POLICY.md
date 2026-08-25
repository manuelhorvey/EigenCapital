# EigenCapital — Capital Tier Promotion Policy

## Promotion Conditions

| From → To | Minimum Days | Zero Incidents | Evidence Required |
|-----------|-------------|----------------|-------------------|
| T1 → T2 | 14 | Yes | Stability, execution quality, reconciliation |
| T2 → T3 | 30 | Yes | Capacity review, liquidity verification |
| T3 → T4 | 60 | Yes | Order slicing assessment, spread analysis |
| T4 → T5 | 90 | Yes | Institutional readiness review |

## HOLD Conditions

Trading at current tier continues if:
- No promotion evidence exists
- No safety violations occurred
- System is stable
- Operator has not authorized promotion

## ROLLBACK Conditions

Automatic rollback to previous tier if:
- Critical incident at current tier
- Reconciliation failure
- Risk limit breach
- Execution quality degradation
- Position protection failure
- Fingerprint mismatch

### Rollback Mechanism

```python
# Automatic rollback on incident
governor.activate_tier("T1-QUALIFICATION")  # Return to previous tier
```

After rollback:
- Observation clock resets to 0
- New evidence collection begins
- Promotion requires full evidence from current tier

## FREEZE Conditions

System enters FROZEN state if:
- Repeated recovery failures (3+ disconnects without reconciliation)
- Duplicate process detected
- Fingerprint mismatch cannot be resolved
- Corrupted state detected

FROZEN requires explicit operator intervention to resume.

## Override Prevention

- No manual capital change bypasses tier governance
- No profit-based override — promotion is engineering evidence
- No operator can directly set `active_tier` — must use `promote()`
- All promotion decisions are auditable

## Emergency Rollback

If any safety control fails:
```python
# Immediate demotion
governor.activate_tier("T1-QUALIFICATION")
```

This is always allowed regardless of current tier.
