PYTHON ?= python3
CMAKE ?= cmake
CLONE_TYPE ?= type1
LIMIT ?= 100
SELECTION_ROLE ?= tuning
CASES_DIR ?= benchmarks/bigclonebench/cases
BIGCLONEBENCH_CASE_OPTIONS = $(if $(CANDIDATE_LIMIT),--candidate-limit "$(CANDIDATE_LIMIT)") $(if $(DEDUPE),--dedupe "$(DEDUPE)") $(if $(TEXT_CHANGE),--text-change "$(TEXT_CHANGE)")

.PHONY: help configure build test test-unit test-repository-analysis test-xml test-source test-policy benchmark-repo benchmark-repos history-scaling history-results bigclonebench-preflight bigclonebench-cases bigclonebench

help:
	@printf '%s\n' 'Available targets:'
	@printf '  %-28s %s\n' 'make build' 'Configure and build srcMove'
	@printf '  %-28s %s\n' 'make test' 'Build and run every correctness suite'
	@printf '  %-28s %s\n' 'make test-unit' 'Run all Python unit tests'
	@printf '  %-28s %s\n' 'make test-repository-analysis' 'Run repository-analysis unit tests'
	@printf '  %-28s %s\n' 'make test-xml' 'Build and run XML regression tests'
	@printf '  %-28s %s\n' 'make test-source' 'Build and run source-pair regression tests'
	@printf '  %-28s %s\n' 'make test-policy' 'Build and run reviewer-editable move-policy tests'
	@printf '  %-28s %s\n' 'make benchmark-repo' 'Run and save CASE repository benchmark'
	@printf '  %-28s %s\n' 'make benchmark-repos' 'Run the explicit standard repository suite'
	@printf '  %-28s %s\n' 'make history-scaling' 'Measure history throughput across JOBS'
	@printf '  %-28s %s\n' 'make history-results' 'Show moves from the latest repository history'
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

test-repository-analysis:
	$(PYTHON) tests/run.py --suite repository-analysis

test-xml: build
	$(PYTHON) tests/run.py --suite xml

test-source: build
	$(PYTHON) tests/run.py --suite source

test-policy: build
	$(PYTHON) tests/run.py --suite policy

benchmark-repo:
	@test -n "$(CASE)" || { echo 'error: CASE is required'; exit 2; }
	@$(PYTHON) benchmarks/repositories/run_case.py "$(CASE)" \
		$(if $(OLD_REV),--old-rev "$(OLD_REV)") \
		$(if $(NEW_REV),--new-rev "$(NEW_REV)") \
		$(if $(DIRECTORY),--directory "$(DIRECTORY)") \
		$(if $(SERIES),--series "$(SERIES)") \
		$(if $(filter 1 yes true,$(UPDATE)),--fetch) \
		$(if $(filter 1 yes true,$(OFFLINE)),--offline)

benchmark-repos:
	@$(PYTHON) benchmarks/repositories/run.py \
		$(if $(SUITE),--suite "$(SUITE)") \
		$(if $(SERIES),--series "$(SERIES)") \
		$(if $(CASE),--case "$(CASE)") \
		$(if $(EXCLUDE_CASE),--exclude-case "$(EXCLUDE_CASE)") \
		$(if $(filter 1 yes true,$(LIST)),--list) \
		$(if $(filter 1 yes true,$(UPDATE)),--fetch) \
		$(if $(filter 1 yes true,$(OFFLINE)),--offline)

history-scaling:
	@test -n "$(CASE)" || { echo 'error: CASE is required'; exit 2; }
	@test -n "$(START)" || { echo 'error: START is required'; exit 2; }
	@test -n "$(COUNT)" || { echo 'error: COUNT is required'; exit 2; }
	@test -n "$(JOBS)" || { echo 'error: JOBS is required'; exit 2; }
	@$(PYTHON) benchmarks/repositories/benchmark_history_scaling.py "$(CASE)" \
		--start "$(START)" --count "$(COUNT)" --jobs "$(JOBS)" \
		$(if $(REPETITIONS),--repetitions "$(REPETITIONS)") \
		$(if $(WARMUPS),--warmups "$(WARMUPS)") \
		$(if $(SEED),--seed "$(SEED)") \
		$(if $(LABEL),--label "$(LABEL)") \
		$(if $(ENVIRONMENT_LABEL),--environment-label "$(ENVIRONMENT_LABEL)") \
		$(if $(DATA_ROOT),--data-root "$(DATA_ROOT)") \
		$(if $(SCRATCH_ROOT),--scratch-root "$(SCRATCH_ROOT)") \
		$(if $(DIRECTORY),--directory "$(DIRECTORY)") \
		$(if $(RETENTION),--retention "$(RETENTION)") \
		$(if $(filter 1 yes true,$(UPDATE)),--fetch) \
		$(if $(filter 1 yes true,$(OFFLINE)),--offline)

history-results:
	@$(PYTHON) benchmarks/repositories/run_history.py show \
		$(if $(HISTORY),"$(HISTORY)") \
		$(if $(PAIR),--pair "$(PAIR)") \
		$(if $(filter 1 yes true,$(DIFF)),--diff) \
		$(if $(filter 1 yes true,$(VERBOSE)),--verbose)

bigclonebench-preflight:
	@$(PYTHON) benchmarks/bigclonebench/pipeline.py preflight

bigclonebench-cases:
	@$(PYTHON) benchmarks/bigclonebench/pipeline.py cases \
		--clone-type "$(CLONE_TYPE)" --limit "$(LIMIT)" \
		--selection-role "$(SELECTION_ROLE)" $(BIGCLONEBENCH_CASE_OPTIONS) \
		--out-dir "$(CASES_DIR)"

bigclonebench: bigclonebench-cases
	@$(PYTHON) benchmarks/bigclonebench/pipeline.py benchmark \
		--clone-type "$(CLONE_TYPE)" --cases-dir "$(CASES_DIR)" \
		--srcdiff /workspace/srcDiff/build/bin/srcdiff \
		--srcmove /workspace/srcMove/build/srcMove
