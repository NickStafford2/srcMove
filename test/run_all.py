#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class TestStep:
    name: str
    command: list[str]
    env: dict[str, str] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run srcMove's normal test suite from one place."
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Configure and build before running tests.",
    )
    parser.add_argument(
        "--include-stress",
        action="store_true",
        help="Also run long stress tests.",
    )
    return parser.parse_args()


def find_srcdiff() -> Path | None:
    from_path = shutil.which("srcdiff")
    if from_path:
        return Path(from_path)

    candidates = [
        REPO_ROOT.parent / "srcDiff" / "build" / "bin" / "srcdiff",
        REPO_ROOT.parent / "srcDiff" / "build-release-check" / "bin" / "srcdiff",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def env_with_srcdiff(srcdiff: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    if srcdiff is not None:
        env["PATH"] = f"{srcdiff.parent}{os.pathsep}{env.get('PATH', '')}"
    return env


def run_step(step: TestStep) -> bool:
    print()
    print(f"=== {step.name} ===", flush=True)
    print(" ".join(step.command), flush=True)
    result = subprocess.run(step.command, cwd=REPO_ROOT, env=step.env, check=False)
    if result.returncode == 0:
        print(f"PASS {step.name}")
        return True
    print(f"FAIL {step.name} (exit code {result.returncode})")
    return False


def build_steps(args: argparse.Namespace) -> list[TestStep]:
    srcdiff = find_srcdiff()
    test_env = env_with_srcdiff(srcdiff)

    steps: list[TestStep] = []
    if args.build:
        steps.extend(
            [
                TestStep("configure", ["cmake", "-S", ".", "-B", "build", "-G", "Ninja"]),
                TestStep("build", ["ninja", "-C", "build"]),
            ]
        )

    steps.extend(
        [
            TestStep(
                "custom e2e",
                [sys.executable, "test/e2e_custom/run_tests.py", "build/srcMove"],
                test_env,
            ),
            TestStep(
                "generated e2e",
                [sys.executable, "test/e2e_generated/run_tests.py"],
                test_env,
            ),
        ]
    )

    if args.include_stress:
        steps.append(TestStep("stress", [sys.executable, "test/stress/run_tests.py"], test_env))

    return steps


def main() -> int:
    args = parse_args()

    srcmove = REPO_ROOT / "build" / "srcMove"
    if not args.build and not srcmove.is_file():
        print("error: build/srcMove not found; rerun with --build", file=sys.stderr)
        return 2

    srcdiff = find_srcdiff()
    if srcdiff is None:
        print("error: srcdiff not found on PATH or in ../srcDiff/build/bin", file=sys.stderr)
        return 2
    print(f"using srcdiff: {srcdiff}", flush=True)

    steps = build_steps(args)
    failed = 0
    for step in steps:
        if not run_step(step):
            failed += 1

    print()
    print("=== Test Summary ===")
    print(f"steps run: {len(steps)}")
    print(f"failures : {failed}")
    print("excluded : stress unless --include-stress")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
