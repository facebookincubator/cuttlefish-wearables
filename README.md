# cuttlefish-wearables — macOS/darwin Cuttlefish host-tools patch series

This repo packages the darwin (macOS) Cuttlefish host-tools work as a **public,
reproducible patch series** on top of public AOSP.

- **`default.xml` / `minimal.xml`** — a minimal `repo` manifest (274 projects) pinned to
  public **`android.googlesource.com`** revisions. It is the trimmed set needed to build
  `out/host/darwin-x86/cvd-host_package.tar.gz` for `aosp_cf_arm64_phone`. Each project is
  pinned to an exact public SHA; the bases cluster around the **BP2A.250325.001** build
  (Android 16 beta, March 2025).
- **`patches/<repo>/NNNN-*.patch`** — the changes to apply, numbered per repo, in order.
- **`apply.sh`** — applies every repo's series with `git am`.

## Prerequisite (macOS): a case-sensitive volume

macOS's default filesystem is **case-insensitive**, which breaks AOSP checkouts (source
files that differ only in case collide). Create a case-sensitive sparse volume and do all
work inside it:

```bash
# create a growable, case-sensitive 500 GB sparse volume named "AOSP"
hdiutil create -type SPARSEBUNDLE -fs HFS+ -fsargs -s -size 500g \
  -volname 'AOSP' "$HOME/AOSP.sparseimage"

# mount it at /Volumes/AOSP (re-run this line to remount after a reboot)
hdiutil attach "$HOME/AOSP.sparseimage.sparsebundle" -mountpoint /Volumes/AOSP

cd /Volumes/AOSP   # do repo init / sync / build here
```

Notes:
- `-fsargs -s` forwards `-s` to `newfs_hfs`, which makes the HFS+ volume
  **case-sensitive** (HFSX). Without it, HFS+ is case-insensitive and AOSP won't build.
- `hdiutil create` appends `.sparsebundle`, so the file to `attach` is
  `$HOME/AOSP.sparseimage.sparsebundle`.
- The image grows on demand up to 500 GB (a full checkout + build needs a few hundred GB).
- To reclaim freed space later: `hdiutil compact "$HOME/AOSP.sparseimage.sparsebundle"`.

## Usage

```bash
cd /Volumes/AOSP                                   # the case-sensitive volume from above
repo init -u <this-repo-url> -m default.xml        # or copy default.xml in and -u the AOSP mirror
repo sync -c -j8

# apply the darwin patch series
/path/to/cuttlefish-wearables/apply.sh "$PWD"

# build (darwin host). vendor/qcom/proprietary is intentionally absent, so the qcom
# vendorsetup that normally exports SDCLANG_* is gone — provide a harmless stub:
cat > /tmp/sdclang.json <<'JSON'
{"default":{"FORCE_SDCLANG_OFF":true,"SDCLANG":false,"SDCLANG_PATH":"prebuilts/clang/host/darwin-x86/bin"}}
JSON
export SDCLANG_AE_CONFIG=/tmp/sdclang.json SDCLANG_CONFIG=/tmp/sdclang.json SDCLANG_CONFIG_AOSP=/tmp/sdclang.json

. build/envsetup.sh && lunch aosp_cf_arm64_phone-userdebug
m out/host/darwin-x86/cvd-host_package.tar.gz
```

## How the patches were produced

Each Phabricator diff (`D…`) was resolved to its commit, then **cherry-picked onto the
repo's public-AOSP base** in a scratch worktree and exported with `git format-patch`
(verifying the series applies on the public base). Internal code names were redacted from
commit messages. Other internal metadata (author `@meta.com` emails, `phabricator.intern`
URLs, reviewer handles) is left intact by request.

## Coverage (130 listed changes)

- **124 patches generated & verified** to apply on their public base (in `patches/`).
- **1 realized by the manifest** — `D77878830` *Add missing darwin platform tools*
  (`aosp/manifest`): the extra darwin tool projects are already present in `default.xml`.
- **3 need a manual rebase** (they were authored on the qcom/keystone tree and conflict on
  pure AOSP — not included in `patches/`):
  - `D79568107` *libjpeg compatible with darwin* (`external/libjpeg-turbo`): modifies the
    Qualcomm-only file `qcjpegcode.h`, which does not exist in AOSP.
  - `D89554877` *Adding flag to disable setting fstab_suffix* (`device/google/cuttlefish`):
    context conflict in `host/commands/assemble_cvd/flags.cc`.
  - `D90353685` *add the rest of dev monitor logic* (`device/google/cuttlefish`): context
    conflict in `assemble_cvd/flags.cc` / `flags_defaults.h`.
- **2 need manual extraction** — their repos are `clone-depth=1` shallow, so the pre-change
  parent isn't available locally to diff:
  - `D78132232` *Fix encoding detection on mac for kconfig parse* (`device/google/cuttlefish_prebuilts`)
  - `D79568265` *include libunwind for darwin* (`prebuilts/rust`)

  To extract each: `git fetch` the public parent, then
  `git format-patch -1 <commit>`. Public parents:
  `cuttlefish_prebuilts` → `b94cdb4076e0137668c651423c481b82c3b10e8e`,
  `prebuilts/rust` → `383c3c04e1ba14c4722f0fd0aa30e2c406cc45c8`.

## Notes

- Manifest revisions are exact public SHAs (no tag-name guessing). Bases span a few nearby
  BP2A builds (Dec 2024 – Mar 2025); this is a pinned snapshot, not a single coherent
  release manifest. If you prefer one coherent base, `repo init` an Android 16 / BP2A
  manifest and apply these patches (minor rebasing may be needed).
- `vendor/meta/build` (internal `.jfconfig`) and other Meta-internal repos are excluded.
