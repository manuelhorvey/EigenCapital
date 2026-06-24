import os
import json
from paper_trading.state_store import StateStore
from shared.metrics.attribution import compute_aggregate_domain_scores
from shared.metrics.mae_mfe import compute_mae_mfe_stats

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE_DIR)

def test():
    all_records = _STORE.read_attribution(limit=500)
    print(f"Read {len(all_records)} attribution records.")
    if not all_records:
        print("No records found.")
        return

    try:
        domain_scores = compute_aggregate_domain_scores(all_records)
        print("Domain scores computed.")
    except Exception as e:
        print(f"Error computing domain scores: {e}")
        import traceback
        traceback.print_exc()

    try:
        mae_mfe = compute_mae_mfe_stats(all_records)
        print("MAE/MFE stats computed.")
    except Exception as e:
        print(f"Error computing MAE/MFE stats: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
