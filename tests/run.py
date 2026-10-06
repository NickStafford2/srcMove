#!/usr/bin/env python3
"""Inventory and run all correctness contracts; benchmarks use this same suite."""
from __future__ import annotations

import argparse
from collections import Counter
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from benchmarking.tooling import find_srcdiff, find_srcmove, run_command

SUITES = ("unit", "behavior", "tooling")
COMPONENTS = ("canonical_forms", "selection_policy", "sequence_similarity", "shadow_classifier", "location_context")


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


class ComponentTest(unittest.TestCase):
    def __init__(self, name, build_dir):
        super().__init__()
        self.name, self.build_dir = name, build_dir

    def id(self):
        return "components." + self.name

    def __str__(self):
        return self.id()

    def runTest(self):
        fixture = REPO_ROOT / "tests/unit/location_context/semantic_containers.xml"
        if self.name == "shadow_diagnostics":
            binary = find_srcmove(REPO_ROOT)
            if binary is None:
                raise RuntimeError("srcMove required for shadow diagnostics")
            command = [sys.executable, str(REPO_ROOT / "tests/unit/shadow_classifier/check_shadow_diagnostics.py"), str(binary), str(fixture)]
        else:
            command = [str(self.build_dir / (self.name + "_test"))]
            if self.name == "location_context":
                command.append(str(fixture))
        artifact = Path(os.environ["SRCMOVE_TEST_ARTIFACTS"]) / self.id()
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "command.json").write_text(json.dumps(command, indent=2))
        executable = Path(command[0])
        (artifact / "executable.json").write_text(json.dumps(tool_identity(executable), indent=2))
        result = run_command(command, cwd=REPO_ROOT)
        (artifact / "stdout.txt").write_text(result.stdout)
        (artifact / "stderr.txt").write_text(result.stderr)
        self.assertEqual(result.returncode, 0, f"component failed; see {artifact}\n{result.stderr}\n{result.stdout}")


def inventory(suites=SUITES, component_build_dir=None):
    loader = unittest.TestLoader()
    tests = []
    for name in dict.fromkeys(suites):
        tests.extend(flatten(loader.discover(str(REPO_ROOT / "tests" / name), top_level_dir=str(REPO_ROOT))))
        if name == "unit":
            build = (component_build_dir or REPO_ROOT / "build").resolve()
            tests.extend(ComponentTest(component, build) for component in (*COMPONENTS, "shadow_diagnostics"))
        if name == "behavior":
            from tests.support.fixture_tests import load_fixture_tests
            tests.extend(flatten(load_fixture_tests()))
            from tests.support.selection_catalog import load_selection_tests
            tests.extend(flatten(load_selection_tests()))
    duplicates = [name for name, count in Counter(test.id() for test in tests).items() if count != 1]
    if duplicates:
        raise ValueError("duplicate test IDs: " + ", ".join(duplicates))
    if loader.errors:
        raise ValueError("discovery failed:\n" + "\n".join(loader.errors))
    return sorted(tests, key=lambda test: test.id())


def select(tests, patterns):
    if not patterns:
        return tests
    for pattern in patterns:
        if not any(fnmatch.fnmatchcase(test.id(), pattern) for test in tests):
            raise ValueError(f"selector matches no tests: {pattern}")
    return [test for test in tests if any(fnmatch.fnmatchcase(test.id(), pattern) for pattern in patterns)]


class RecordedResult(unittest.TextTestResult):
    """One outcome per method/case, including subtest and setup failures."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []
        self.active = None

    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()
        self.active = {"id": test.id(), "status": "pass", "details": []}

    def record(self, test, status, detail):
        if self.active is not None:
            # An error remains an error even if another subtest asserts unsuccessfully.
            rank = {"pass": 0, "skip": 1, "failure": 2, "error": 3}
            if rank[status] > rank[self.active["status"]]:
                self.active["status"] = status
            self.active["details"].append(detail)
        else:
            self.outcomes.append({"id": test.id(), "status": status, "details": [detail], "seconds": 0})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "failure", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", self._exc_info_to_string(err, test))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.record(test, "failure" if issubclass(err[0], test.failureException) else "error", str(subtest) + "\n" + self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skip", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, "failure", "expected-failure contracts are not accepted coverage\n" + self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, "failure", "unexpected success")

    def stopTest(self, test):
        self.active["seconds"] = time.monotonic() - self.started
        self.outcomes.append(self.active)
        self.active = None
        super().stopTest(test)


def tool_identity(path):
    if path is None:
        return None
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", action="append", choices=SUITES)
    parser.add_argument("--test", action="append", default=[], metavar="ID_OR_GLOB", help="Select methods, fixtures, or components by full ID or shell glob; repeat for a union.")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--component-build-dir", type=Path, default=REPO_ROOT / "build")
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "build/test-results")
    parser.add_argument("--report", type=Path, help="JSON inventory/outcomes; defaults to ARTIFACTS/report.json")
    return parser.parse_args()


def main():
    args = parse_args()
    suites = args.suite or list(SUITES)
    try:
        tests = select(inventory(suites, args.component_build_dir), args.test)
        if not tests:
            raise ValueError("no tests selected")
        if args.list:
            for test in tests:
                print(test.id())
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps({"inventory": [test.id() for test in tests]}, indent=2) + "\n")
            return 0
        srcmove = find_srcmove(REPO_ROOT, args.srcmove)
        srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
        for name, tool, explicit in (("SRCMOVE_BIN", srcmove, args.srcmove), ("SRCDIFF_BIN", srcdiff, args.srcdiff)):
            if explicit is not None and tool is None:
                raise ValueError(f"executable not found: {explicit}")
            if tool is not None:
                os.environ[name] = str(tool)
        args.artifacts.mkdir(parents=True, exist_ok=True)
        os.environ["SRCMOVE_TEST_ARTIFACTS"] = str(args.artifacts.resolve())
        result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(unittest.TestSuite(tests))
        counts = Counter(item["status"] for item in result.outcomes)
        report = {"inventory": [test.id() for test in tests], "outcomes": result.outcomes, "counts": dict(counts), "tools": {"srcmove": tool_identity(srcmove), "srcdiff": tool_identity(srcdiff)}, "component_build_dir": str(args.component_build_dir.resolve()), "artifacts": str(args.artifacts.resolve())}
        # Suite/class setup errors are separate outcomes, and their unexecuted IDs stay visible.
        executed = {item["id"] for item in result.outcomes}
        report["not_executed"] = sorted(set(report["inventory"]) - executed)
        report_path = args.report or args.artifacts / "report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Outcomes: {dict(counts)}; report: {report_path}")
        return int(bool(counts["failure"] or counts["error"] or counts["skip"] or report["not_executed"]))
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
