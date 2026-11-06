#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
# Apply Cuttlefish patches with Git's attribution-preserving three-way fallback.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
readonly SCRIPT_DIR

exec "${SCRIPT_DIR}/apply.sh" --3way "$@"
