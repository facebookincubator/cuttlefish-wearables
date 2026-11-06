#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.
# SPDX-License-Identifier: Apache-2.0
# Apply Cuttlefish patch series using the Python helper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
readonly SCRIPT_DIR

exec python3 "${SCRIPT_DIR}/scripts/apply_patches.py" "$@"
