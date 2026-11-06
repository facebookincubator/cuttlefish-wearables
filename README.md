# Cuttlefish on macOS

This repo packages Meta Wearables' changes for running Cuttlefish host tools
natively on macOS and Apple silicon as patches to public AOSP.

This is a **publish-only** repository. We do not accept pull requests at this
time. See [CONTRIBUTING.md](CONTRIBUTING.md) for upstream contribution guidance.

- **`default.xml` / `minimal.xml`** — identical reduced manifests, with 274 projects.
  Most use `android-16.0.0_r1`; `packages/modules/WebViewBootstrap` tracks `main`.
  These are not per-project SHA-pinned snapshots.
- **`patches/<repo>/NNNN-*.patch`** — changes numbered per project, in order.
- **`apply.sh`** — applies the series to an existing checkout, or syncs a new one
  with `--sync` before applying.
- **`apply-robust.sh`** — uses `git am --3way`; conflicts still need manual review.

The patches were developed against BP2A.250325.001 / Android 16 beta. A source-only
check found that SwiftShader's first patch fails at `Android.bp:93` on the
manifest's release tag; that series needs rebasing before the full bundle applies.

## Prerequisites

Patch application and the helper tests require Git and Python 3.9 or newer.
Syncing a new AOSP checkout also requires Android's `repo` tool on `PATH`.
Native macOS emulation requires
[qemu-wearables](https://github.com/facebookincubator/qemu-wearables).
Follow that repository's build instructions; QEMU is not included in this bundle.

## Check patches first

Check the bundle before downloading an AOSP source checkout:

```bash
git clone https://github.com/facebookincubator/cuttlefish-wearables.git
PATCH_REPO="${PWD}/cuttlefish-wearables"
python3 -B "${PATCH_REPO}/scripts/check_patches.py"
```

This uses temporary shallow, blobless clones of only the patched projects at their
manifest revisions. It applies each series to Git's index, without checking out
source files, and returns nonzero if any series fails. Temporary clones are removed
afterward; an existing AOSP checkout is untouched. Internet access is required.
This checks diff application, not build/boot behavior or `git am` metadata.
Resolve any failures before proceeding to a full checkout.

## Prepare a case-sensitive volume (macOS)

AOSP has filenames that differ only in case, so use a case-sensitive volume:

```bash
hdiutil create -type SPARSEBUNDLE -fs HFS+ -fsargs -s -size 500g \
  -volname 'AOSP' "${HOME}/AOSP.sparseimage"
hdiutil attach "${HOME}/AOSP.sparseimage.sparsebundle" -mountpoint /Volumes/AOSP
```

`-fsargs -s` makes the volume case-sensitive (HFSX). The sparse bundle grows as
needed, and `hdiutil create` appends `.sparsebundle` to the filename.

## Sync a new AOSP checkout and apply

Configure your Git committer name and email first. From the patch repository:

```bash
./apply.sh --sync /Volumes/AOSP/aosp
```

`--sync` accepts only a new or empty directory. It runs `repo init` using this
patch repository's committed manifest, **`repo sync -c -j8`** to fetch the AOSP
projects, and `repo manifest -r -o aosp-base.xml` to record their exact base
revisions. Only after those steps succeed does it apply the patches. Uncommitted
manifest or patch edits are refused. A failed sync is left for manual recovery.

## Apply to an existing synced checkout

```bash
./apply.sh /Volumes/AOSP/aosp
```

This uses the existing checkout as-is: no `repo init`, sync, or reset is performed.
It should use the manifest and base revisions described above. Save the unpatched
revisions with `repo manifest -r` if you did not already do so.

Both helpers check all projects before applying anything, refuse dirty or missing
projects and unfinished Git operations, and stop on failure without cleanup.
They create local commits, preserving patch authors and messages. If `git am`
fails, resolve with `git am --continue` or abandon that project's series with
`git am --abort`, then apply the remaining project series manually.
**Rerunning the whole script is not a resume operation.** The three-way helper
requires the original base blobs locally and never falls back to fuzzy patching.

## Build the macOS host package

Run only after successful application:

```bash
cd /Volumes/AOSP/aosp
source build/envsetup.sh \
  && lunch aosp_cf_arm64_phone-bp2a-userdebug \
  && m out/host/darwin-x86/cvd-host_package.tar.gz
```

Application is not proof of a successful build or boot.

## Test the helpers

```bash
python3 -B -m unittest discover -s tests -v
```

Tests run offline in disposable Git repositories or with mocked `repo` commands.
They do not fetch AOSP, build, or boot an emulator.

With Pylint and ShellCheck installed, lint from the repository root:

```bash
PYTHONPATH="${PWD}" pylint scripts/*.py tests/*.py
shellcheck apply.sh apply-robust.sh
```

## License and contributions

Meta's helper scripts, manifests, and documentation are licensed under the
[Apache License, Version 2.0](LICENSE). The patch files modify AOSP and
third-party source that retains its own copyright and license notices; the
root license does not replace those upstream licenses. See [LICENSE](LICENSE)
and each affected upstream project's license files for details.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributions and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the project's Code of Conduct.
