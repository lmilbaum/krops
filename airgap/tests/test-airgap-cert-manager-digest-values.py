#!/usr/bin/env python3
"""Require the airgap cert-manager pods to reference the bundled image digests.

Zarf stores a `tag@sha256` image by digest only, but rewrites a tag-only pod
image to a `<tag>-zarf-<crc>` name that was never pushed, so the pull fails
(ImagePullBackOff). airgap/values/cert-manager.yaml must therefore pin each
image by the same digest airgap/images.txt bundles.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_TXT = REPO_ROOT / "airgap/images.txt"
VALUES = REPO_ROOT / "airgap/values/cert-manager.yaml"

# values.yaml key path (indent-aware) -> images.txt image name
COMPONENTS = {
    None: "quay.io/jetstack/cert-manager-controller",
    "cainjector": "quay.io/jetstack/cert-manager-cainjector",
    "webhook": "quay.io/jetstack/cert-manager-webhook",
    "startupapicheck": "quay.io/jetstack/cert-manager-startupapicheck",
}


def bundled_digests() -> dict[str, str]:
    found = {}
    for line in IMAGES_TXT.read_text().splitlines():
        match = re.match(r"^(?P<name>\S+?):[^@\s]+@(?P<digest>sha256:[a-f0-9]{64})\s*$", line)
        if match:
            found[match["name"]] = match["digest"]
    return found


def values_digests() -> dict[str | None, str]:
    found: dict[str | None, str] = {}
    section: str | None = None
    for line in VALUES.read_text().splitlines():
        top = re.match(r"^([a-zA-Z]+):\s*$", line)
        if top:
            section = top[1]
        digest = re.match(r"^\s+digest:\s*(sha256:[a-f0-9]{64})\s*$", line)
        if digest:
            # controller digest lives under top-level `image:`, others under `<component>.image:`
            found[None if section == "image" else section] = digest[1]
    return found


def main() -> None:
    bundled, pinned = bundled_digests(), values_digests()
    errors = []
    for key, image in COMPONENTS.items():
        label = key or "controller"
        if pinned.get(key) is None:
            errors.append(f"{VALUES}: no image digest set for cert-manager {label}")
        elif pinned[key] != bundled.get(image):
            errors.append(f"{label}: values pin {pinned[key]}, images.txt bundles {bundled.get(image)}")
    if errors:
        sys.exit("cert-manager digest values check FAILED:\n  " + "\n  ".join(errors))

    print("cert-manager digest values check OK")


if __name__ == "__main__":
    main()
