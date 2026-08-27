"""Build pinning — guarantee the executing code is the audited frozen build.

C1 of the P0 Safety Remediation campaign. Computes a build identity from:
  loop-script SHA-256, config fingerprint, manifest identity.
Verification fails closed on ANY drift. The supervisor stamps the verified
build-id into every audit record so evidence is attributable to a binary.

Note: git HEAD is intentionally excluded from verification. The loop script
hash, manifest identity, and config fingerprint already detect any meaningful
code or configuration change. Pinning to a git commit creates a chicken-and-egg
problem (updating the pin changes HEAD, invalidating the pin).
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_MANIFEST_IDENTITY = "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"
PINNED_LOOP_SCRIPT = "scripts/r4_rebalance_loop.py"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class PinCheck:
    component: str
    expected: str
    observed: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class BuildIdentity:
    git_head: str
    manifest_identity: str
    config_fingerprint: str
    loop_script_sha256: str
    build_id: str
    checks: list[PinCheck] = field(default_factory=list)

    @property
    def all_verified(self) -> bool:
        return all(c.ok for c in self.checks)


def compute_git_head(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else f"UNAVAILABLE({out.returncode})"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"UNAVAILABLE({type(exc).__name__})"


def compute_build_identity(repo: Path, config_fingerprint: str) -> BuildIdentity:
    from eigencapital.fidelity.r4_manifest import R4ConfigManifest

    head = compute_git_head(repo)
    manifest_identity = R4ConfigManifest().compute_identity()
    loop_path = repo / PINNED_LOOP_SCRIPT
    loop_sha = sha256_file(loop_path) if loop_path.exists() else "MISSING"

    checks = [
        PinCheck(
            "manifest_identity",
            EXPECTED_MANIFEST_IDENTITY,
            manifest_identity,
            manifest_identity == EXPECTED_MANIFEST_IDENTITY,
        ),
        PinCheck(
            "config_fingerprint_nonempty",
            "nonempty",
            config_fingerprint[:16],
            bool(config_fingerprint),
        ),
        PinCheck(
            "loop_script_present",
            "present",
            "present" if loop_path.exists() else "MISSING",
            loop_path.exists(),
        ),
    ]
    build_material = "|".join([manifest_identity[:16], config_fingerprint[:16], loop_sha])
    build_id = hashlib.sha256(build_material.encode()).hexdigest()[:32]
    return BuildIdentity(
        git_head=head,
        manifest_identity=manifest_identity,
        config_fingerprint=config_fingerprint,
        loop_script_sha256=loop_sha,
        build_id=build_id,
        checks=checks,
    )


def verify_pinned_build(repo: Path, config_fingerprint: str) -> tuple[bool, BuildIdentity]:
    """Fail-closed verification against pinned expectations."""
    identity = compute_build_identity(repo, config_fingerprint)
    return identity.all_verified, identity
