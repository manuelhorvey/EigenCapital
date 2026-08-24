"""Feature dependency DAG and resolution.

Features often depend on other features. For example:
- momentum_zscore depends on return (lookback) and volatility
- distance_from_SMA depends on SMA
- normalized_range depends on ATR

The dependency DAG ensures features are computed in the correct order,
and that all prerequisites are available before computing derived features.

This module:
1. Defines the dependency graph
2. Resolves computation order (topological sort)
3. Detects circular dependencies
4. Validates that all dependencies can be satisfied
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from enum import Enum


class DependencyType(str, Enum):
    """Type of dependency between features."""
    HARD = "hard"    # Feature cannot be computed without this dependency
    SOFT = "soft"    # Feature can be computed with degraded output without this


@dataclass(frozen=True)
class FeatureDependency:
    """A single dependency edge in the feature DAG.

    Attributes:
        feature_id: The feature that depends on something
        depends_on: The feature it depends on
        dependency_type: Whether this is a hard or soft dependency
        description: Why this dependency exists
    """
    feature_id: str
    depends_on: str
    dependency_type: DependencyType = DependencyType.HARD
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "depends_on": self.depends_on,
            "dependency_type": self.dependency_type.value,
            "description": self.description,
        }


@dataclass
class FeatureDAG:
    """Directed Acyclic Graph of feature dependencies.

    Resolves computation order and detects circular dependencies.
    """
    _edges: Dict[str, List[FeatureDependency]] = field(default_factory=dict)
    _reverse_edges: Dict[str, List[FeatureDependency]] = field(default_factory=dict)

    def add_dependency(self, dependency: FeatureDependency) -> None:
        """Add a dependency edge to the DAG."""
        if dependency.feature_id not in self._edges:
            self._edges[dependency.feature_id] = []
        self._edges[dependency.feature_id].append(dependency)

        if dependency.depends_on not in self._reverse_edges:
            self._reverse_edges[dependency.depends_on] = []
        self._reverse_edges[dependency.depends_on].append(dependency)

    def get_dependencies(self, feature_id: str) -> List[str]:
        """Get direct dependencies of a feature."""
        if feature_id not in self._edges:
            return []
        return [dep.depends_on for dep in self._edges[feature_id]]

    def get_dependents(self, feature_id: str) -> List[str]:
        """Get features that depend on this feature."""
        if feature_id not in self._reverse_edges:
            return []
        return [dep.feature_id for dep in self._reverse_edges[feature_id]]

    def resolve_order(self, requested: List[str]) -> List[str]:
        """Resolve computation order for requested features.

        Returns features in topological order (dependencies first).

        Args:
            requested: List of feature IDs to compute

        Returns:
            List of feature IDs in computation order

        Raises:
            ValueError: If circular dependency detected
            ValueError: If requested feature not in DAG
        """
        # Collect all transitive dependencies
        all_needed: Set[str] = set()
        for fid in requested:
            self._collect_transitive(fid, all_needed, visited=set())

        # Topological sort using Kahn's algorithm
        in_degree: Dict[str, int] = {fid: 0 for fid in all_needed}
        for fid in all_needed:
            for dep in self.get_dependencies(fid):
                if dep in all_needed:
                    in_degree[fid] += 1

        # Start with nodes that have no dependencies
        queue = [fid for fid in all_needed if in_degree[fid] == 0]
        result: List[str] = []

        while queue:
            # Sort for deterministic output
            queue.sort()
            node = queue.pop(0)
            result.append(node)

            for dependent in self.get_dependents(node):
                if dependent in all_needed:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        if len(result) != len(all_needed):
            missing = all_needed - set(result)
            raise ValueError(
                f"Circular dependency detected. Unresolved features: {missing}"
            )

        return result

    def _collect_transitive(
        self, feature_id: str, collected: Set[str], visited: Set[str]
    ) -> None:
        """Collect all transitive dependencies."""
        if feature_id in visited:
            return
        visited.add(feature_id)

        for dep in self.get_dependencies(feature_id):
            self._collect_transitive(dep, collected, visited)

        collected.add(feature_id)

    def validate_dag(self) -> List[str]:
        """Validate the entire DAG for circular dependencies.

        Returns list of errors (empty if valid).
        """
        errors: List[str] = []
        all_nodes = set(self._edges.keys()) | set(self._reverse_edges.keys())

        for node in all_nodes:
            visited: Set[str] = set()
            try:
                self._check_cycle(node, visited, set())
            except ValueError as e:
                errors.append(str(e))

        return errors

    def _check_cycle(
        self, node: str, visited: Set[str], recursion_stack: Set[str]
    ) -> None:
        """DFS cycle detection."""
        if node in recursion_stack:
            raise ValueError(f"Circular dependency involving {node}")
        if node in visited:
            return

        visited.add(node)
        recursion_stack.add(node)

        for dep in self.get_dependencies(node):
            self._check_cycle(dep, visited, recursion_stack)

        recursion_stack.discard(node)

    @property
    def all_features(self) -> Set[str]:
        """All features in the DAG."""
        return set(self._edges.keys()) | set(self._reverse_edges.keys())

    @property
    def root_features(self) -> Set[str]:
        """Features with no dependencies (leaf nodes of the DAG)."""
        return self.all_features - set(self._edges.keys())


# ──────────────────────────────────────────────
#  Default dependency graph for known features
# ──────────────────────────────────────────────

def build_default_dag() -> FeatureDAG:
    """Build the default dependency DAG for EigenCapital's feature set.

    This captures the known relationships between features.
    New features should be added here as they are implemented.
    """
    dag = FeatureDAG()

    # Momentum z-score depends on return and volatility
    dag.add_dependency(FeatureDependency(
        feature_id="momentum_zscore",
        depends_on="return",
        dependency_type=DependencyType.HARD,
        description="Momentum z-score normalizes return by volatility",
    ))
    dag.add_dependency(FeatureDependency(
        feature_id="momentum_zscore",
        depends_on="volatility",
        dependency_type=DependencyType.HARD,
        description="Momentum z-score normalizes return by volatility",
    ))

    # Distance from SMA depends on SMA
    dag.add_dependency(FeatureDependency(
        feature_id="distance_from_sma",
        depends_on="sma",
        dependency_type=DependencyType.HARD,
        description="Distance is computed relative to SMA",
    ))

    # Distance from EMA depends on EMA
    dag.add_dependency(FeatureDependency(
        feature_id="distance_from_ema",
        depends_on="ema",
        dependency_type=DependencyType.HARD,
        description="Distance is computed relative to EMA",
    ))

    # MA crossover depends on SMA (two windows)
    dag.add_dependency(FeatureDependency(
        feature_id="ma_crossover",
        depends_on="sma",
        dependency_type=DependencyType.HARD,
        description="MA crossover compares two SMA windows",
    ))

    # Dual momentum depends on return
    dag.add_dependency(FeatureDependency(
        feature_id="dual_momentum",
        depends_on="return",
        dependency_type=DependencyType.HARD,
        description="Dual momentum uses returns at two horizons",
    ))

    # Bollinger position depends on SMA and volatility
    dag.add_dependency(FeatureDependency(
        feature_id="bollinger_position",
        depends_on="sma",
        dependency_type=DependencyType.HARD,
        description="Bollinger bands are centered on SMA",
    ))
    dag.add_dependency(FeatureDependency(
        feature_id="bollinger_position",
        depends_on="volatility",
        dependency_type=DependencyType.HARD,
        description="Bollinger band width depends on volatility",
    ))

    # Bollinger bandwidth depends on SMA and volatility
    dag.add_dependency(FeatureDependency(
        feature_id="bollinger_bandwidth",
        depends_on="sma",
        dependency_type=DependencyType.HARD,
        description="Bandwidth is computed from SMA-based bands",
    ))
    dag.add_dependency(FeatureDependency(
        feature_id="bollinger_bandwidth",
        depends_on="volatility",
        dependency_type=DependencyType.HARD,
        description="Bandwidth depends on standard deviation",
    ))

    # Z-score depends on SMA and volatility
    dag.add_dependency(FeatureDependency(
        feature_id="rolling_zscore",
        depends_on="sma",
        dependency_type=DependencyType.HARD,
        description="Z-score = (value - mean) / std",
    ))
    dag.add_dependency(FeatureDependency(
        feature_id="rolling_zscore",
        depends_on="volatility",
        dependency_type=DependencyType.HARD,
        description="Z-score = (value - mean) / std",
    ))

    # ATR depends on true range
    dag.add_dependency(FeatureDependency(
        feature_id="atr",
        depends_on="true_range",
        dependency_type=DependencyType.HARD,
        description="ATR is smoothed true range",
    ))

    # Volume ratio depends on volume MA
    dag.add_dependency(FeatureDependency(
        feature_id="volume_ratio",
        depends_on="volume_ma",
        dependency_type=DependencyType.HARD,
        description="Volume ratio = current volume / volume MA",
    ))

    return dag
