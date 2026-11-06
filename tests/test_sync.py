# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for opt-in syncing; repo and network commands are mocked."""

import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import apply_patches


class SyncNewCheckoutTests(unittest.TestCase):
    """Verify sync safety and command order without downloading AOSP."""

    def setUp(self):
        self.root = pathlib.Path(
            tempfile.mkdtemp(prefix="cuttlefish-sync-test-")
        )
        self.addCleanup(shutil.rmtree, self.root)
        self.checkout = self.root / "new aosp"
        self.patch_repository = self.root / "patch repository"
        self.revision = "a" * 40
        self.git_mock = self.enter_context(mock.patch.object(
            apply_patches, "git_output",
            side_effect=["", "Fixture committer", self.revision],
        ))
        self.enter_context(mock.patch.object(
            apply_patches.shutil, "which", return_value="/fake/repo",
        ))
        self.commands = self.enter_context(mock.patch.object(
            apply_patches.subprocess, "run",
        ))

    def enter_context(self, context):
        """Register mock cleanup using the Python 3.9 unittest API."""
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value

    def test_new_checkout_runs_init_sync_and_manifest_in_order(self):
        """Pin the manifest, sync projects, and record their bases."""
        apply_patches.sync_new_checkout(self.checkout, self.patch_repository)
        self.assertTrue(self.checkout.is_dir())
        actual = [call.args[0] for call in self.commands.call_args_list]
        self.assertEqual(actual,
                         [
                             ["repo", "init", "-u", str(self.patch_repository),
                              "-b", self.revision, "-m", "default.xml"],
                             ["repo", "sync", "-c", "-j8"],
                             ["repo", "manifest", "-r", "-o",
                              "aosp-base.xml"],
                         ])
        for call in self.commands.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.checkout)
            self.assertTrue(call.kwargs["check"])

    def test_existing_tree_is_refused_without_writes(self):
        """Leave existing source trees and local files untouched."""
        self.checkout.mkdir()
        marker = self.checkout / "precious"
        marker.write_text("keep")
        with self.assertRaisesRegex(RuntimeError, "new or empty"):
            apply_patches.sync_new_checkout(self.checkout,
                                            self.patch_repository)
        self.commands.assert_not_called()
        self.git_mock.assert_not_called()
        self.assertEqual(marker.read_text(), "keep")

    def test_uncommitted_bundle_is_refused_before_directory_creation(self):
        """Do not start a sync with uncommitted manifest or patch edits."""
        self.git_mock.side_effect = None
        self.git_mock.return_value = " M default.xml"
        with self.assertRaisesRegex(RuntimeError, "Commit manifest/patch"):
            apply_patches.sync_new_checkout(self.checkout,
                                            self.patch_repository)
        self.commands.assert_not_called()
        self.assertFalse(self.checkout.exists())

    def test_missing_repo_is_refused_before_directory_creation(self):
        """Fail without filesystem writes when the repo tool is unavailable."""
        with mock.patch.object(apply_patches.shutil, "which",
                               return_value=None):
            with self.assertRaisesRegex(RuntimeError, "repo tool"):
                apply_patches.sync_new_checkout(self.checkout,
                                                self.patch_repository)
        self.commands.assert_not_called()
        self.assertFalse(self.checkout.exists())

    def test_failed_sync_does_not_run_manifest_or_apply(self):
        """Stop after sync failure without running the manifest command."""
        self.commands.side_effect = [
            None, subprocess.CalledProcessError(1, ["repo", "sync"]),
        ]
        with self.assertRaisesRegex(RuntimeError, "sync failed; no patches"):
            apply_patches.sync_new_checkout(self.checkout,
                                            self.patch_repository)
        self.assertEqual(self.commands.call_count, 2)
        self.assertTrue(self.checkout.is_dir())

    def test_default_command_uses_existing_checkout_without_sync(self):
        """Use an existing checkout without initializing or syncing it."""
        with mock.patch.object(apply_patches, "sync_new_checkout") as sync:
            with mock.patch.object(apply_patches, "apply_all_patches") as apply:
                with mock.patch("sys.argv", ["apply.sh", str(self.checkout)]):
                    self.assertEqual(apply_patches.main(), 0)
        sync.assert_not_called()
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0], self.checkout)

    def test_failed_sync_command_never_applies_patches(self):
        """Return failure without applying patches after a sync error."""
        with mock.patch.object(apply_patches, "sync_new_checkout",
                               side_effect=RuntimeError("sync failed")):
            with mock.patch.object(apply_patches, "apply_all_patches") as apply:
                with mock.patch("sys.argv", ["apply.sh", "--sync",
                                             str(self.checkout)]):
                    self.assertEqual(apply_patches.main(), 1)
        apply.assert_not_called()

    def test_sync_command_applies_only_after_successful_sync(self):
        """Apply patches only after the requested sync finishes successfully."""
        events = []
        with mock.patch.object(apply_patches, "sync_new_checkout",
                               side_effect=lambda *args: events.append("sync")):
            with mock.patch.object(apply_patches, "apply_all_patches",
                                   side_effect=lambda *args:
                                   events.append("apply")):
                with mock.patch("sys.argv", ["apply.sh", "--sync",
                                             str(self.checkout)]):
                    self.assertEqual(apply_patches.main(), 0)
        self.assertEqual(events, ["sync", "apply"])


if __name__ == "__main__":
    unittest.main()
