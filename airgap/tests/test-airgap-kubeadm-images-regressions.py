#!/usr/bin/env python3
"""Offline regressions for kubeadm inventory validation and correction."""
import contextlib
import hashlib
import http.client
import importlib.util
import io
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).with_name("test-airgap-kubeadm-images.py")
spec = importlib.util.spec_from_file_location("kubeadm_images", SOURCE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
DIGEST = "sha256:" + "a" * 64
EXPECTED = {name: "v1.2.3" for name in gate.TRACKED_COMPONENTS}


def section(category, omit=()):
    return f"# ── Images [{category}] ──\n" + "".join(
        f"{name}:{tag}@{DIGEST}\n"
        for name, tag in sorted(EXPECTED.items()) if name not in omit
    )


class InventoryTests(unittest.TestCase):
    def run_gate(self, text, fix=False):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "images.txt"
            inventory.write_text(text)
            with patch.object(gate, "IMAGES_TXT", inventory), \
                 patch.object(gate, "target_kubernetes_version", return_value="1.2.3"), \
                 patch.object(gate, "kubeadm_expected_images", return_value=EXPECTED) as kubeadm, \
                 patch.object(gate, "registry_digest", return_value=DIGEST) as registry, \
                 patch.object(sys, "argv", [str(SOURCE)] + (["--fix"] if fix else [])), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                result = gate.main()
            return result, inventory.read_text(), kubeadm.call_count, registry.call_count

    def assert_invalid(self, text):
        for fix in (False, True):
            with self.subTest(fix=fix):
                result, after, kubeadm, registry = self.run_gate(text, fix)
                self.assertEqual(result, 1)
                self.assertEqual(after, text)
                self.assertEqual((kubeadm, registry), (0, 0))

    def test_empty_workload(self):
        self.assert_invalid(section("M") + section("H") + section("W", EXPECTED))

    def test_empty_management(self):
        self.assert_invalid(section("M", EXPECTED) + section("H") + section("W"))

    def test_partial_component(self):
        self.assert_invalid(section("M") + section("W", ["registry.k8s.io/pause"]))

    def test_missing_section(self):
        self.assert_invalid(section("M"))
        self.assert_invalid(section("W"))

    def test_missing_header(self):
        self.assert_invalid(section("M") + section("H") + section("W").split("\n", 1)[1])

    def test_duplicate_section(self):
        self.assert_invalid(section("M") + section("W") + section("W"))

    def test_complete(self):
        text = section("M") + section("H") + section("W")
        for fix in (False, True):
            result, after, _, _ = self.run_gate(text, fix)
            self.assertEqual(result, 0)
            self.assertEqual(after, text)

    def test_wrong_tag_and_digest(self):
        complete = section("M") + section("W")
        for broken in (complete.replace(":v1.2.3@", ":v0.0.0@", 1),
                       complete.replace(DIGEST, "sha256:" + "b" * 64, 1)):
            with self.subTest(broken=broken):
                self.assertEqual(self.run_gate(broken)[0], 1)
                result, after, _, _ = self.run_gate(broken, True)
                self.assertEqual(result, 0)
                self.assertEqual(after, complete)


class RegistryDigestTests(unittest.TestCase):
    """Tests for registry_digest() digest-source logic."""

    def _make_response(self, header=None, body=b"some body bytes"):
        msg = http.client.HTTPMessage()
        if header is not None:
            msg["Docker-Content-Digest"] = header
        resp = unittest.mock.MagicMock()
        resp.headers = msg
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        return resp

    def test_prefers_header(self):
        header_digest = "sha256:" + "c" * 64
        fake = self._make_response(header=header_digest, body=b"transformed")
        with unittest.mock.patch.object(gate.urllib.request, "urlopen", return_value=fake):
            result = gate.registry_digest("registry.example.com/img", "latest")
        self.assertEqual(result, header_digest)
        fake.read.assert_not_called()

    def test_falls_back_to_body_without_header(self):
        body = b"raw manifest bytes"
        fake = self._make_response(header=None, body=body)
        with unittest.mock.patch.object(gate.urllib.request, "urlopen", return_value=fake):
            result = gate.registry_digest("registry.example.com/img", "latest")
        expected = "sha256:" + hashlib.sha256(body).hexdigest()
        self.assertEqual(result, expected)

    def test_ignores_malformed_header(self):
        body = b"raw manifest bytes"
        fake = self._make_response(header="md5:abc", body=body)
        with unittest.mock.patch.object(gate.urllib.request, "urlopen", return_value=fake):
            result = gate.registry_digest("registry.example.com/img", "latest")
        expected = "sha256:" + hashlib.sha256(body).hexdigest()
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
