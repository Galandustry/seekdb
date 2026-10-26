#!/usr/bin/env python3
# Copyright (c) 2025 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"""Build the real IK classifier and compare it to an original Git revision."""

import argparse
import pathlib
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--baseline-ref", default="76f871eb5a84b664d487b03b3412ce50194135b5")
    parser.add_argument("--baseline-header", type=pathlib.Path,
                        help="original header exported with git show (for cross-OS worktrees)")
    parser.add_argument("--build-dir", default="build_fts_checks")
    parser.add_argument("--bench", action="store_true")
    parser.add_argument("--sanitizers", action="store_true")
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[3]
    build = (root / args.build_dir).resolve()
    build.mkdir(parents=True, exist_ok=True)
    if args.baseline_header:
        original = args.baseline_header.read_text(encoding="utf-8-sig")
    else:
        original = subprocess.check_output(
            ["git", "show", f"{args.baseline_ref}:src/storage/fts/ik/ob_ik_char_util.h"],
            cwd=root, text=True, encoding="utf-8")
    original = original.replace("ObFTCharUtil", "BaselineFTCharUtil").replace(
        "_OCEANBASE_STORAGE_FTS_IK_OB_IK_CHAR_UTIL_H_", "_BASELINE_FTS_CHAR_UTIL_H_")
    baseline = build / "baseline_char_util.h"
    baseline.write_text(original, encoding="utf-8")
    executable = build / "test_ik_char_util"
    command = [
        args.compiler, "-std=gnu++17", "-O2", "-ffunction-sections", "-fdata-sections",
        "-Isrc", "-Isrc/oblib", "-I.",
        f'-DFTS_BASELINE_HEADER="{baseline.as_posix()}"',
        "unittest/storage/fts/test_ik_char_util.cpp",
        "src/storage/fts/utils/unicode_utils.cpp", "-Wl,--gc-sections", "-o", str(executable)]
    if args.sanitizers:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    print(f"Baseline: {args.baseline_header or args.baseline_ref}", flush=True)
    subprocess.run([args.compiler, "--version"], cwd=root, check=True)
    subprocess.run(command, cwd=root, check=True)
    subprocess.run([str(executable)] + (["--bench"] if args.bench else []), cwd=root, check=True)


if __name__ == "__main__":
    main()
