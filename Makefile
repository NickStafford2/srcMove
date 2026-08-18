PYTHON ?= python3
CMAKE ?= cmake
CLONE_TYPE ?= type1
LIMIT ?= 100
SELECTION_ROLE ?= tuning
CASES_DIR ?= benchmarks/bigclonebench/cases
BIGCLONEBENCH_CASE_OPTIONS = $(if $(CANDIDATE_LIMIT),--candidate-limit "$(CANDIDATE_LIMIT)") $(if $(DEDUPE),--dedupe "$(DEDUPE)") $(if $(TEXT_CHANGE),--text-change "$(TEXT_CHANGE)")

.PHONY: help configure build test test-unit test-xml test-source benchmark-repo bigclonebench-preflight bigclonebench-cases bigclonebench

help:
	@printf '%s\n' 'Available targets:'
	@printf '  %-28s %s\n' 'make build' 'Configure and build srcMove'
	@printf '  %-28s %s\n' 'make test' 'Build and run every correctness suite'
	@printf '  %-28s %s\n' 'make test-unit' 'Run Python infrastructure tests'
	@printf '  %-28s %s\n' 'make test-xml' 'Build and run XML regression tests'
	@printf '  %-28s %s\n' 'make test-source' 'Build and run source-pair regression tests'
	@printf '  %-28s %s\n' 'make benchmark-repo' 'Run and save CASE repository benchmark'
	@printf '  %-28s %s\n' 'make bigclonebench-preflight' 'Check the local BigCloneBench installation'
	@printf '  %-28s %s\n' 'make bigclonebench-cases' 'Generate a configurable BigCloneBench case slice'
	@printf '  %-28s %s\n' 'make bigclonebench' 'Generate cases and run the staged BigCloneBench pipeline'

configure:
	$(CMAKE) -S . -B build -G Ninja

build: configure
	$(CMAKE) --build build

test: build
	$(PYTHON) tests/run.py

test-unit:
	$(PYTHON) tests/run.py --suite unit

test-xml: build
	$(PYTHON) tests/run.py --suite xml

test-source: build
	$(PYTHON) tests/run.py --suite source

benchmark-repo:
	@test -n "$(CASE)" || { echo 'error: CASE is required'; exit 2; }
	$(PYTHON) benchmarks/repositories/run_case.py "$(CASE)" \
		$(if $(SERIES),--series "$(SERIES)") \
		$(if $(filter 1 yes true,$(UPDATE)),--fetch) \
		$(if $(filter 1 yes true,$(OFFLINE)),--offline)

bigclonebench-preflight:
	$(PYTHON) benchmarks/bigclonebench/pipeline.py preflight

bigclonebench-cases:
	$(PYTHON) benchmarks/bigclonebench/pipeline.py cases \
		--clone-type "$(CLONE_TYPE)" --limit "$(LIMIT)" \
		--selection-role "$(SELECTION_ROLE)" $(BIGCLONEBENCH_CASE_OPTIONS) \
		--out-dir "$(CASES_DIR)"

bigclonebench: bigclonebench-cases
	$(PYTHON) benchmarks/bigclonebench/pipeline.py benchmark \
		--clone-type "$(CLONE_TYPE)" --cases-dir "$(CASES_DIR)" \
		--srcdiff /workspace/srcDiff/build/bin/srcdiff \
		--srcmove /workspace/srcMove/build/srcMove
