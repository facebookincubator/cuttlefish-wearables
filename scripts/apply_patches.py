#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
"""Apply numbered Cuttlefish patches to clean AOSP projects."""

import argparse
import os
import pathlib
import shutil
import subprocess
import sys


GIT_OPERATIONS = (
    "rebase-apply", "rebase-merge", "MERGE_HEAD", "CHERRY_PICK_HEAD",
    "REVERT_HEAD", "sequencer", "index.lock",
)


def git_environment() -> dict[str, str]:
    """Return a Git environment without inherited repository overrides."""
    environment = os.environ.copy()
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        environment.pop(name, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def git_output(project_directory: pathlib.Path, *arguments: str) -> str:
    """Return stripped Git output, raising RuntimeError on command failure."""
    result = subprocess.run(
        ["git", "-C", str(project_directory), *arguments],
        capture_output=True, text=True, env=git_environment(), check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Git failed in {project_directory}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def find_patch_series(
    patch_directory: pathlib.Path,
) -> list[tuple[pathlib.Path, list[pathlib.Path]]]:
    """Return project-relative paths and ordered files from the patch bundle."""
    patch_files = list(patch_directory.rglob("*.patch"))
    if not patch_files:
        raise RuntimeError(f"No patches found in {patch_directory}")
    if any(patch.is_symlink() for patch in patch_files):
        raise RuntimeError("Patch files must not be symlinks")
    directories = sorted({patch.parent for patch in patch_files})
    # The bundle uses zero-padded numbers, so filename order is correct.
    return [
        (directory.relative_to(patch_directory),
         sorted(directory.glob("*.patch")))
        for directory in directories
    ]


def check_project(
    project_directory: pathlib.Path, aosp_root: pathlib.Path,
) -> None:
    """Require a clean, standalone Git project inside the resolved AOSP root.

    Raise RuntimeError for missing projects, hidden edits, unfinished Git
    operations, or an unavailable committer identity. Never clean up edits.
    """
    if not project_directory.is_relative_to(aosp_root):
        raise RuntimeError(f"Project escapes AOSP root: {project_directory}")
    if not (project_directory / ".git").exists():
        raise RuntimeError(f"Missing Git project: {project_directory}")
    git_root = pathlib.Path(
        git_output(project_directory, "rev-parse", "--show-toplevel")
    ).resolve()
    if git_root != project_directory:
        raise RuntimeError(f"Not a standalone Git project: {project_directory}")
    for operation in GIT_OPERATIONS:
        operation_path = pathlib.Path(
            git_output(project_directory, "rev-parse", "--git-path", operation)
        )
        if not operation_path.is_absolute():
            operation_path = project_directory / operation_path
        if operation_path.exists():
            raise RuntimeError(
                f"Unfinished Git operation in {project_directory}: {operation}"
            )
    entries = git_output(project_directory, "ls-files", "-v").splitlines()
    if any(entry[:1].islower() or entry.startswith("S") for entry in entries):
        raise RuntimeError(
            f"Masked index entries in {project_directory}; unmask them manually"
        )
    if git_output(project_directory, "status", "--porcelain",
                  "--untracked-files=all"):
        raise RuntimeError(
            f"Dirty project: {project_directory}; preserve work before applying"
        )
    git_output(project_directory, "var", "GIT_COMMITTER_IDENT")


def apply_patch_series(
    project_directory: pathlib.Path,
    patch_files: list[pathlib.Path],
    three_way: bool,
) -> None:
    """Apply a series with git am, retaining authorship and failed sessions."""
    original_head = git_output(project_directory, "rev-parse", "HEAD")
    options = ["--keep-cr", "--3way" if three_way else "--no-3way"]
    print(f"== git am: {project_directory} ==", flush=True)
    try:
        subprocess.run(
            ["git", "-C", str(project_directory), "am", *options,
             *[str(patch) for patch in patch_files]],
            check=True, env=git_environment(),
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Stopped in {project_directory}. Resolve with git am --continue, "
            "or abort with git am --abort; apply remaining series manually."
        ) from error
    commits_created = int(git_output(
        project_directory, "rev-list", "--count", f"{original_head}..HEAD",
    ))
    if commits_created != len(patch_files):
        raise RuntimeError(
            f"Some patches were skipped in {project_directory}; review manually"
        )


def apply_all_patches(
    aosp_root: pathlib.Path,
    patch_directory: pathlib.Path,
    three_way: bool = False,
) -> None:
    """Preflight all projects, then apply their series, stopping on error."""
    aosp_root = aosp_root.resolve(strict=True)
    series = find_patch_series(patch_directory)
    # Check every project before creating any commits; recheck before use.
    for project_name, _ in series:
        check_project((aosp_root / project_name).resolve(), aosp_root)
    for project_name, patch_files in series:
        project_directory = (aosp_root / project_name).resolve()
        check_project(project_directory, aosp_root)
        apply_patch_series(project_directory, patch_files, three_way)
    print("All patch series applied cleanly.")


def sync_new_checkout(
    aosp_root: pathlib.Path, patch_repository: pathlib.Path,
) -> None:
    """Sync an empty AOSP directory at the patch repository's manifest commit.

    Refuse existing source trees or uncommitted manifests/patches. A failed
    sync is left intact for manual recovery; no automatic cleanup is done.
    """
    if aosp_root.exists() and any(aosp_root.iterdir()):
        raise RuntimeError("--sync requires a new or empty AOSP directory")
    if git_output(patch_repository, "status", "--porcelain",
                  "--untracked-files=all", "--", "default.xml", "patches"):
        raise RuntimeError("Commit manifest/patch edits before using --sync")
    if shutil.which("repo") is None:
        raise RuntimeError("--sync requires the Android repo tool on PATH")
    git_output(patch_repository, "var", "GIT_COMMITTER_IDENT")
    manifest_revision = git_output(patch_repository, "rev-parse", "HEAD")
    aosp_root.mkdir(parents=True, exist_ok=True)
    commands = (
        ["repo", "init", "-u", str(patch_repository), "-b",
         manifest_revision, "-m", "default.xml"],
        ["repo", "sync", "-c", "-j8"],
        ["repo", "manifest", "-r", "-o", "aosp-base.xml"],
    )
    for command in commands:
        print(f"Running: {' '.join(command)}", flush=True)
        try:
            subprocess.run(command, cwd=aosp_root, env=git_environment(),
                           check=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"repo {command[1]} failed; no patches applied. "
                "Recover the sync manually before running apply.sh again."
            ) from error


def main() -> int:
    """Run the command-line helper and return a nonzero status on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aosp_root", nargs="?", type=pathlib.Path,
                        default=pathlib.Path.cwd())
    parser.add_argument("--3way", dest="three_way", action="store_true",
                        help="use Git's three-way fallback")
    parser.add_argument("--sync", action="store_true",
                        help="sync a new or empty AOSP directory")
    arguments = parser.parse_args()
    patch_repository = pathlib.Path(__file__).resolve().parents[1]
    try:
        if arguments.sync:
            sync_new_checkout(arguments.aosp_root.resolve(), patch_repository)
        apply_all_patches(arguments.aosp_root, patch_repository / "patches",
                          arguments.three_way)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
