#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_ROOT = Path(__file__).resolve().parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from tooling import (
    command_text,
    environment_with_tool,
    find_srcdiff,
    find_srcmove,
    run_command,
)


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
    parser.add_argument(
        "--include-bigclonebench",
        action="store_true",
        help="Also run the one-case generated BigCloneBench Type-1 smoke test.",
    )
    return parser.parse_args()


def run_step(step: TestStep) -> bool:
    print()
    print(f"=== {step.name} ===", flush=True)
    print(command_text(step.command), flush=True)
    result = run_command(
        step.command,
        cwd=REPO_ROOT,
        env=step.env,
        capture_output=False,
    )
    if result.returncode == 0:
        print(f"PASS {step.name}")
        return True
    print(f"FAIL {step.name} (exit code {result.returncode})")
    return False


def build_steps(args: argparse.Namespace, srcmove: Path) -> list[TestStep]:
    srcdiff = find_srcdiff(REPO_ROOT)
    test_env = environment_with_tool(srcdiff) if srcdiff is not None else None

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
                "python unit tests",
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "test",
                    "-p",
                    "test_*.py",
                ],
            ),
            TestStep(
                "custom e2e",
                [sys.executable, "test/e2e_custom/run_tests.py", str(srcmove)],
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

    if args.include_bigclonebench:
        steps.append(
            TestStep(
                "bigclonebench type-1",
                [
                    sys.executable,
                    "test/e2e_bigclonebench/run_tests.py",
                    "--limit",
                    "1",
                    "--srcmove",
                    str(srcmove),
                ],
                test_env,
            )
        )

    return steps


def main() -> int:
    args = parse_args()

    srcmove = REPO_ROOT / "build" / "srcMove" if args.build else find_srcmove(REPO_ROOT)
    if not args.build and srcmove is None:
        print("error: build/srcMove not found; rerun with --build", file=sys.stderr)
        return 2

    srcdiff = find_srcdiff(REPO_ROOT)
    if srcdiff is None:
        print("error: srcdiff not found on PATH or in ../srcDiff/build/bin", file=sys.stderr)
        return 2
    print(f"using srcdiff: {srcdiff}", flush=True)

    assert srcmove is not None
    steps = build_steps(args, srcmove)
    failed = 0
    for step in steps:
        if not run_step(step):
            failed += 1

    print()
    print("=== Test Summary ===")
    print(f"steps run: {len(steps)}")
    print(f"failures : {failed}")
    print("excluded : BigCloneBench unless --include-bigclonebench; stress unless --include-stress")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
