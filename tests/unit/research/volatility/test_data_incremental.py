"""Data contract: frozen manifests verify; candidate classification
vocabulary is closed; LOO/insertion counters behave."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.volatility import config as C
from research.volatility import data as DATA
from research.volatility import evidence as E
from research.volatility import incremental as INC


def test_supplement_manifest_verifies():
    m = DATA.verify_manifest(C.SUPPLEMENT_MANIFEST)
    assert "combined_sha256" in m


def test_candidate_manifest_verifies():
    m = DATA.verify_manifest(C.CANDIDATE_MANIFEST)
    assert "combined_sha256" in m


def test_r5_frozen_snapshot_verifies():
    DATA.verify_r5_frozen_snapshot()  # raises on any drift


def test_no_new_files_in_frozen_dir():
    names = [p.name for p in C.FROZEN_DIR.iterdir() if p.name.endswith("_D1.csv")]
    with open(C.FROZEN_MANIFEST) as fh:
        import json

        frozen = json.load(fh)
    assert set(names) == set(frozen["per_file_prefixes"])


def _feats(n: int = 12, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = [f"A{i}" for i in range(n)]
    return pd.DataFrame(rng.normal(size=(n, 9)), index=idx, columns=[f"f{j}" for j in range(9)])


def test_loo_report_structure():
    out = INC.loo_report(_feats())
    assert out["base_k"] >= 2
    assert len(out["assets"]) == 12
    # ARI is bounded [-1, 1]; negative is possible when a leave-one-out
    # assignment disagrees with the full-set clustering
    assert np.isnan(out["ari_min"]) or -1.0 <= out["ari_min"] <= 1.0


def test_candidate_classification_vocabulary_closed():
    base = _feats(seed=1)
    # candidate far away on first feature
    cand_row = base.iloc[[0]].copy()
    cand_row.index = ["CAND"]
    cand_row.iloc[0, 0] = 50.0
    rep = INC.candidate_report(base, "CAND", cand_row)
    assert rep["classification"] in {
        E.STRUCTURALLY_DISTINCT,
        E.STRUCTURALLY_REDUNDANT,
        E.INCONCLUSIVE,
    }


def test_candidate_report_nearest_neighbors_listed():
    base = _feats(seed=2)
    cand_row = base.iloc[[1]].copy()
    cand_row.index = ["CAND"]
    rep = INC.candidate_report(base, "CAND", cand_row)
    assert len(rep["nearest_neighbors"]) == C.NEAREST_NEIGHBORS
    names = [n for n, _ in rep["nearest_neighbors"]]
    assert "CAND" not in names


def test_dataset_loads_all_baseline_assets():
    bundle = DATA.load_dataset(verify=False)
    assert len(bundle.baseline) == 34
    assert set(C.CANDIDATE_ASSETS) <= set(bundle.candidates) | {"USOIL"}
