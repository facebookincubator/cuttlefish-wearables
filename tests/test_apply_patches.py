# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
"""Offline checks using small, disposable Git repositories."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = pathlib.Path(__file__).resolve().parents[1]


class PatchApplicationTests(unittest.TestCase):
    """Exercise command-line application against isolated Git fixtures."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="cuttlefish-test-"))
        self.addCleanup(shutil.rmtree, self.root)
        self.bundle = self.root / "patch bundle"
        self.checkout = self.root / "aosp checkout"
        self.source = self.root / "source"
        self.environment = os.environ.copy()
        for name in list(self.environment):
            if name.startswith("GIT_"):
                self.environment.pop(name)
        self.environment.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
        )
        (self.bundle / "scripts").mkdir(parents=True)
        shutil.copy2(SOURCE / "scripts/apply_patches.py",
                     self.bundle / "scripts")
        for name in ("apply.sh", "apply-robust.sh"):
            shutil.copy2(SOURCE / name, self.bundle / name)
        self.source.mkdir()
        self.git(self.source, "init", "-q")
        self.configure_identity(self.source)
        (self.source / "file").write_text("base\n")
        self.git(self.source, "add", "file")
        self.git(self.source, "commit", "-qm", "base")
        self.base_commit = self.git(self.source, "rev-parse", "HEAD")
        patch_directory = self.bundle / "patches/project a"
        patch_directory.mkdir(parents=True)
        for contents in ("first", "second"):
            (self.source / "file").write_text(contents + "\n")
            self.git(self.source, "add", "file")
            self.git(self.source, "commit", "-qm", contents,
                     "--author=Original author <author@example.invalid>")
        self.git(self.source, "format-patch", "-q", "--output-directory",
                 str(patch_directory), self.base_commit)
        shutil.copytree(patch_directory, self.bundle / "patches/project z")
        self.make_checkout()

    def git(self, directory, *arguments):
        """Run a fixture Git command and assert that it succeeds."""
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            env=self.environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def configure_identity(self, directory):
        """Use synthetic authorship only inside the disposable repositories."""
        self.git(directory, "config", "user.name", "Fixture committer")
        self.git(directory, "config", "user.email", "committer@example.invalid")

    def make_checkout(self):
        """Recreate both target projects at their unpatched base."""
        if self.checkout.exists():
            shutil.rmtree(self.checkout)
        self.checkout.mkdir()
        for name in ("project a", "project z"):
            directory = self.checkout / name
            self.git(self.checkout, "clone", "-q", str(self.source),
                     str(directory))
            self.git(directory, "checkout", "-q", "--detach", self.base_commit)
            self.configure_identity(directory)

    def run_helper(self, robust=False, environment=None):
        """Run the application entry point against the fixture checkout."""
        script = "apply-robust.sh" if robust else "apply.sh"
        return subprocess.run(
            ["bash", str(self.bundle / script), str(self.checkout)],
            env=environment or self.environment, capture_output=True, text=True,
            check=False,
        )

    def assert_failure(self, result, message):
        """Require a nonzero exit and the expected diagnostic."""
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stdout + result.stderr)

    def assert_first_project_unchanged(self):
        """Assert preflight prevented commits in the earlier clean project."""
        self.assertEqual(
            self.git(self.checkout / "project a", "rev-parse", "HEAD"),
            self.base_commit,
        )

    def test_ordered_application_preserves_attribution_and_paths(self):
        """Apply dependent patches in order with original authorship."""
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        project = self.checkout / "project a"
        self.assertEqual((project / "file").read_text(), "second\n")
        self.assertEqual(
            self.git(project, "rev-list", "--count",
                     f"{self.base_commit}..HEAD"),
            "2",
        )
        self.assertEqual(
            self.git(project, "log", "-2", "--format=%ae").splitlines(),
            ["author@example.invalid"] * 2,
        )

    def test_dirty_and_masked_edits_block_all_application(self):
        """Preserve visible and hidden edits before any project is patched."""
        for mode in ("unstaged", "staged", "untracked", "assume-unchanged",
                     "skip-worktree"):
            with self.subTest(mode=mode):
                self.make_checkout()
                project = self.checkout / "project z"
                filename = "untracked" if mode == "untracked" else "file"
                path = project / filename
                if mode in ("assume-unchanged", "skip-worktree"):
                    self.git(project, "update-index", "--" + mode, "file")
                path.write_text("precious\n")
                if mode == "staged":
                    self.git(project, "add", "file")
                expected = (
                    "Masked index entries"
                    if mode in ("assume-unchanged", "skip-worktree")
                    else "Dirty project"
                )
                self.assert_failure(self.run_helper(), expected)
                self.assert_first_project_unchanged()
                self.assertEqual(path.read_text(), "precious\n")

    def test_missing_project_blocks_all_application(self):
        """Refuse missing projects before patching the earlier clean project."""
        shutil.rmtree(self.checkout / "project z")
        self.assert_failure(self.run_helper(), "Missing Git project")
        self.assert_first_project_unchanged()

    def test_failure_retains_am_and_does_not_clean_up_on_rerun(self):
        """Retain failed am state and earlier commits for manual recovery."""
        patch = self.bundle / "patches/project a/0002-second.patch"
        patch.write_text(patch.read_text().replace("-first\n", "-not-first\n"))
        self.assert_failure(self.run_helper(), "Stopped in")
        project = self.checkout / "project a"
        self.assertEqual((project / "file").read_text(), "first\n")
        self.assertTrue((project / ".git/rebase-apply").exists())
        self.assert_failure(self.run_helper(), "Unfinished Git operation")
        self.assertTrue((project / ".git/rebase-apply").exists())
        self.assertEqual(
            self.git(self.checkout / "project z", "rev-parse", "HEAD"),
            self.base_commit,
        )

    def test_three_way_entry_point_preserves_attribution(self):
        """Preserve original authors through the three-way wrapper."""
        result = self.run_helper(robust=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.git(self.checkout / "project a", "log", "-1", "--format=%ae"),
            "author@example.invalid",
        )

    def test_automatic_three_way_skip_is_not_success(self):
        """Require one commit per patch, rejecting automatic git am skips."""
        for name in ("project a", "project z"):
            (self.bundle / "patches" / name / "0002-second.patch").unlink()
        project = self.checkout / "project a"
        self.git(project, "am",
                 str(self.bundle / "patches/project a/0001-first.patch"))
        previous_head = self.git(project, "rev-parse", "HEAD")
        self.assert_failure(self.run_helper(robust=True),
                            "Some patches were skipped")
        self.assertEqual(self.git(project, "rev-parse", "HEAD"), previous_head)

    def test_git_environment_cannot_redirect_application(self):
        """Ignore Git environment overrides pointing outside the checkout."""
        environment = self.environment.copy()
        environment["GIT_DIR"] = str(self.source / ".git")
        environment["GIT_WORK_TREE"] = str(self.source)
        result = self.run_helper(environment=environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.source / "file").read_text(), "second\n")

    def run_quick_check(self, revision="refs/tags/check-base"):
        """Run the source checker with local file URLs, never the internet."""
        shutil.copy2(SOURCE / "scripts/check_patches.py",
                     self.bundle / "scripts")
        self.git(self.source, "tag", "check-base", self.base_commit)
        self.git(self.source, "config", "uploadpack.allowFilter", "true")
        (self.bundle / "default.xml").write_text(
            f'<manifest><remote name="local" fetch="{self.root.as_uri()}"/>'
            f'<default remote="local" revision="{revision}"/>'
            '<project name="source" path="project a"/>'
            '<project name="source" path="project z"/></manifest>'
        )
        temporary_parent = self.root / "check-temp"
        temporary_parent.mkdir()
        environment = self.environment.copy()
        environment["TMPDIR"] = str(temporary_parent)
        result = subprocess.run(
            [sys.executable, "-B",
             str(self.bundle / "scripts/check_patches.py")],
            env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(list(temporary_parent.iterdir()), [])
        return result

    def test_quick_check_applies_dependent_series_without_checkout(self):
        """Advance temporary indexes without changing source checkouts."""
        result = self.run_quick_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2/2 project series passed", result.stdout)
        self.assert_first_project_unchanged()
        self.assertEqual(self.git(self.source, "status", "--porcelain"), "")

    def test_quick_check_reports_failing_patch_and_continues(self):
        """Name the failed patch and continue checking other project series."""
        patch = self.bundle / "patches/project a/0002-second.patch"
        patch.write_text(patch.read_text().replace("-first\n", "-not-first\n"))
        result = self.run_quick_check()
        self.assert_failure(result, "0002-second.patch")
        self.assertIn("1/2 project series passed", result.stdout)
        self.assert_first_project_unchanged()

    def test_quick_check_reports_missing_base_revision(self):
        """Fail clearly when the manifest's requested revision is absent."""
        result = self.run_quick_check(revision="refs/tags/missing-base")
        self.assert_failure(result, "missing-base")
        self.assertIn("0/2 project series passed", result.stdout)
        self.assert_first_project_unchanged()

    def test_project_symlink_cannot_escape_checkout(self):
        """Refuse a project redirected outside the AOSP root."""
        project = self.checkout / "project z"
        outside = self.root / "outside"
        project.rename(outside)
        project.symlink_to(outside, target_is_directory=True)
        self.assert_failure(self.run_helper(), "Project escapes AOSP root")
        self.assert_first_project_unchanged()


if __name__ == "__main__":
    unittest.main()
