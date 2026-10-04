#!/usr/bin/env python3
"""
Gate: kind version in each GCP WireMock CoreDNS patch header must match mise.toml.

The GCP arm's coredns-rewrites.yaml contains kind's full stock Corefile because a
merge patch replaces the entire Corefile key. The header comment ties it to a kind
version. Renovate only bumps mise.toml; this gate goes red until a human regenerates
the Corefile from a kind cluster at the new version:

    kubectl get configmap coredns -n kube-system -o jsonpath='{.data.Corefile}'

Then insert the WireMock rewrite stanzas back in and update the header version.
"""

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MISE_TOML = REPO_ROOT / "mise.toml"
COREFILE_PATCHES = [
    REPO_ROOT / "virtualized-e2e/gcp/wiremock/patches/coredns-rewrites.yaml",
]
HEADER_KIND_RE = re.compile(r"\bkind v(?P<version>[0-9]+(?:\.[0-9]+)+)\b")


def _header_lines(path: Path) -> list[str]:
    lines = []
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            lines.append(line)
        else:
            break
    return lines


def main() -> int:
    failures: list[str] = []

    with MISE_TOML.open("rb") as f:
        mise = tomllib.load(f)
    kind_pin: str | None = mise.get("tools", {}).get("kind")
    if not kind_pin:
        failures.append("no kind pin found in mise.toml [tools]")
        print("kind Corefile pin FAILED:")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    for patch in COREFILE_PATCHES:
        rel = patch.relative_to(REPO_ROOT)
        if not patch.exists():
            failures.append(f"{rel}: missing")
            continue

        header = _header_lines(patch)
        matches = [m.group("version") for line in header for m in HEADER_KIND_RE.finditer(line)]
        if not matches:
            failures.append(f"{rel}: no 'kind vX.Y.Z' version found in the header comment")
            continue

        unique = set(matches)
        if len(unique) > 1:
            failures.append(f"{rel}: header contains conflicting kind versions: {sorted(unique)}")
            continue

        hdr_version = matches[0]
        if hdr_version != kind_pin.lstrip("v"):
            failures.append(
                f"{rel}: header says kind v{hdr_version} but mise.toml pins kind {kind_pin}; "
                "regenerate the Corefile from a kind v"
                + kind_pin
                + " cluster and update the header"
            )

        body = patch.read_text()
        if "Corefile: |" not in body:
            failures.append(f"{rel}: body does not contain 'Corefile: |'")

    if failures:
        print("kind Corefile pin FAILED:")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print(f"kind Corefile pin OK (kind v{kind_pin}, {len(COREFILE_PATCHES)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
