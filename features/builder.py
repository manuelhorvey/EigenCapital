"""DEPRECATED — moved to ``archive.deprecated._builder``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._builder import (  # noqa: F401
    build_features,
    compute_inference_features,
    compute_macro_derived,
    compute_training_data,
    compute_training_data_extended,
    model_path,
)

warnings.warn(
    "features.builder is deprecated. Use features.alpha_features.build_alpha_features instead.",
    DeprecationWarning,
    stacklevel=2,
)
