"""Clustering rule: determinism, tie-breaking, helper contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.volatility import clustering as CL
from research.volatility import config as C


def _two_block_features(n_a: int = 8, n_b: int = 8, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = {}
    # offset all 9 features so the blocks separate under robust scaling too
    offset = np.full(9, 5.0)
    for i in range(n_a):
        rows[f"A{i}"] = rng.normal(0.0, 0.1, size=9)
    for i in range(n_b):
        rows[f"B{i}"] = rng.normal(0.0, 0.1, size=9) + offset
    return pd.DataFrame(rows, index=[f"f{j}" for j in range(9)]).T


def test_cluster_features_deterministic():
    feats = _two_block_features()
    a = CL.cluster_features(feats)
    b = CL.cluster_features(feats)
    assert a.k == b.k
    assert a.labels.equals(b.labels)
    assert a.silhouette == pytest.approx(b.silhouette)


def test_cluster_features_finds_two_blocks():
    feats = _two_block_features()
    fit = CL.cluster_features(feats)
    assert fit.k == 2
    # every A in one cluster, every B in the other
    a_labs = {fit.labels[f"A{i}"] for i in range(8)}
    b_labs = {fit.labels[f"B{i}"] for i in range(8)}
    assert len(a_labs) == 1 and len(b_labs) == 1
    assert a_labs != b_labs


def test_k_choice_within_frozen_candidates():
    feats = _two_block_features()
    fit = CL.cluster_features(feats)
    assert fit.k in C.CLUSTER_K_CANDIDATES


def test_standardize_and_distance_shapes():
    feats = _two_block_features()
    z = CL.standardize(feats)
    assert z.shape == feats.shape
    assert np.allclose(z.mean(axis=0), 0.0, atol=1e-12)
    d = CL._distance(z, "euclidean")
    assert d.shape == (len(feats), len(feats))
    assert np.allclose(np.diag(d), 0.0)
    assert np.allclose(d, d.T)


def test_pca_transform_scores_and_variance():
    feats = _two_block_features()
    pcs, evr = CL.pca_transform(feats)
    assert pcs.shape[0] == len(feats)
    assert np.isclose(evr.sum(), 1.0, atol=1e-10)
    assert np.all(evr >= -1e-12)
    # components ordered by explained variance
    assert np.all(np.diff(evr) <= 1e-12)


def test_cluster_labels_are_series_with_asset_index():
    feats = _two_block_features()
    fit = CL.cluster_features(feats)
    assert isinstance(fit.labels, pd.Series)
    assert set(fit.labels.index) == set(feats.index)
