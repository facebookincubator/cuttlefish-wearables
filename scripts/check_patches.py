#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
"""Check every patch series using temporary blobless, no-checkout clones."""

import argparse
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as element_tree

import apply_patches


def git_output(directory: pathlib.Path, *arguments: str) -> str:
    """Run Git without hooks or prompts in a temporary checking directory."""
    environment = apply_patches.git_environment()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(directory), "-c", "core.hooksPath=/dev/null",
         *arguments],
        capture_output=True, text=True, env=environment, timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def read_project_sources(
    manifest_file: pathlib.Path,
) -> dict[str, tuple[str, str]]:
    """Read project paths, source URLs, and revisions from the flat manifest."""
    manifest = element_tree.parse(manifest_file).getroot()
    defaults = manifest.find("default")
    if defaults is None:
        raise RuntimeError("Manifest has no default revision/remote")
    remotes = {remote.attrib["name"]: remote.attrib["fetch"]
               for remote in manifest.findall("remote")}
    sources = {}
    for project in manifest.findall("project"):
        project_name = project.attrib["name"]
        remote = project.get("remote", defaults.attrib["remote"])
        revision = project.get("revision", defaults.attrib["revision"])
        sources[project.get("path", project_name)] = (
            remotes[remote].rstrip("/") + "/" + project_name, revision,
        )
    return sources


def check_patch_series(
    directory: pathlib.Path,
    source_url: str,
    revision: str,
    patch_files: list[pathlib.Path],
) -> None:
    """Clone a shallow base and advance its index through the ordered series."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    branch = revision.removeprefix("refs/tags/").removeprefix("refs/heads/")
    git_output(directory.parent, "clone", "--depth=1", "--filter=blob:none",
               "--no-checkout", "--single-branch", "--branch", branch,
               source_url, str(directory))
    print(f"  Base: {git_output(directory, 'rev-parse', 'HEAD')}", flush=True)
    git_output(directory, "read-tree", "HEAD")
    for patch in patch_files:
        try:
            git_output(directory, "apply", "--cached", str(patch))
        except RuntimeError as error:
            raise RuntimeError(f"{patch.name}: {error}") from error


def main() -> int:
    """Check the bundled projects and return nonzero if any series fails."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    try:
        series = apply_patches.find_patch_series(root / "patches")
        sources = read_project_sources(root / "default.xml")
        failures = 0
        with tempfile.TemporaryDirectory(prefix="cuttlefish-check-") as temp:
            temporary_root = pathlib.Path(temp).resolve()
            for project_name, patch_files in series:
                print(f"CHECK {project_name}", flush=True)
                try:
                    directory = (temporary_root / project_name).resolve()
                    if not directory.is_relative_to(temporary_root):
                        raise RuntimeError("Project escapes check directory")
                    source_url, revision = sources[project_name.as_posix()]
                    check_patch_series(directory, source_url, revision,
                                       patch_files)
                    print(f"  PASS: {len(patch_files)} patches", flush=True)
                except (OSError, RuntimeError, KeyError,
                        subprocess.TimeoutExpired) as error:
                    failures += 1
                    print(f"  FAIL: {error}", file=sys.stderr, flush=True)
        print(f"{len(series) - failures}/{len(series)} project series passed.")
        return 1 if failures else 0
    except (OSError, RuntimeError, KeyError, element_tree.ParseError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
