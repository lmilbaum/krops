#!/usr/bin/env python3
"""Offline regression fixtures for the ACK permission documentation guard."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ack_scope", Path(__file__).with_name("test-aws-iam-doc-scope.py")
)
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)
HEADING = "### Least-privilege trade-off: the static principal's union scope\n\n"


def grants(actions):
    return HEADING + "- **IAM**: " + ", ".join(f"`{a}`" for a in actions) + "\n"


class ScopeRegressions(unittest.TestCase):
    def test_each_permission_is_required(self):
        # Exact names isolate each permission, including ones currently covered
        # by wildcards/shorthand in the real document.
        for kind, required in scope.REQUIRED_ACTIONS.items():
            kinds = {kind: {"fixture.yaml"}}
            self.assertEqual(scope.scope_failures(kinds, grants(required)), [])
            for action in required:
                with self.subTest(kind=kind, action=action):
                    failures = scope.scope_failures(
                        kinds, grants(a for a in required if a != action)
                    )
                    self.assertEqual(failures, [f"{kind}: {action} not documented in docs/aws-iam.md"])

    def test_only_principal_grants_count(self):
        doc = HEADING + "- **S3**: `s3:ListBucket`. `s3:UntagResource`/`s3:ListTagsForResource` are not needed\n"
        doc += "\n## Per-cluster read-only IAM roles\n`iam:GetRolePolicy`\n"
        actions = scope.principal_actions(doc)
        self.assertTrue(scope.action_present(actions, "s3:ListBucket"))
        for action in ["s3:UntagResource", "s3:ListTagsForResource", "iam:GetRolePolicy"]:
            self.assertFalse(scope.action_present(actions, action))
        self.assertFalse(scope.action_present(scope.principal_actions("`iam:GetRolePolicy`"), "iam:GetRolePolicy"))

    def test_wildcards_and_wrapped_shorthand(self):
        doc = HEADING + "- **S3**: `s3:GetBucket*`/`s3:PutBucket*`\n- **RDS**: `rds:Describe*`; `secretsmanager:CreateSecret`/\n  `TagResource`; `kms:CreateGrant`/`ListGrants`\n"
        actions = scope.principal_actions(doc)
        for action in ["s3:GetBucketPolicy", "s3:PutBucketPolicy", "rds:DescribeDBInstances", "secretsmanager:TagResource", "kms:ListGrants"]:
            self.assertTrue(scope.action_present(actions, action), action)
        for action in ["s3:GetEncryptionConfiguration", "iam:CreateGrant", "secretsmanager:TagResourcePolicy", "kms:ListGrant"]:
            self.assertFalse(scope.action_present(actions, action), action)
        self.assertFalse(scope.action_present({"iam:GetUserPolicy"}, "iam:GetUser"))

    def discover(self, text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixture.yaml").write_text(text)
            return scope.ack_cr_kinds(root, root)

    def test_yaml_order_spacing_and_multiple_documents(self):
        kinds = self.discover('kind: Role\nmetadata: {}\napiVersion: "iam.services.k8s.aws/v1alpha1"\n---\napiVersion: s3.services.k8s.aws/v1alpha1\n# nonadjacent\nmetadata: {}\nkind: Bucket\n---\napiVersion: v1\nkind: ConfigMap\n')
        self.assertEqual(kinds, {"Role": {"fixture.yaml"}, "Bucket": {"fixture.yaml"}})

    def test_unknown_kind_fails(self):
        kinds = self.discover("kind: Unknown\napiVersion: iam.services.k8s.aws/v1alpha1\n")
        self.assertIn("unknown ACK CR kind Unknown in fixture.yaml", scope.scope_failures(kinds, grants([]))[0])

    def test_invalid_yaml_and_ack_kind_fail(self):
        for text in ["kind: [", "apiVersion: iam.services.k8s.aws/v1alpha1\n", "apiVersion: iam.services.k8s.aws/v1alpha1\nkind: []\n"]:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "fixture.yaml"):
                self.discover(text)

    def test_empty_discovery_fails(self):
        self.assertTrue(scope.scope_failures({}, grants([])))


if __name__ == "__main__":
    unittest.main()
