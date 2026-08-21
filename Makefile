PYTHON ?= python3
CMAKE ?= cmake
CLONE_TYPE ?= type1
LIMIT ?= 100
SELECTION_ROLE ?= tuning
CASES_DIR ?= benchmarks/bigclonebench/cases
BIGCLONEBENCH_DATA_ROOT ?= benchmark-data
BIGCLONEBENCH_DATASET ?=
BIGCLONEBENCH_SELECTION_ID ?=
MODE ?= sample
SEED ?= 0
SAMPLE_SIZE ?= 100
ROLE ?= tuning
VERIFY_SOURCE ?= 0
BIGCLONEBENCH_CASE_OPTIONS = $(if $(CANDIDATE_LIMIT),--candidate-limit "$(CANDIDATE_LIMIT)") $(if $(DEDUPE),--dedupe "$(DEDUPE)") $(if $(TEXT_CHANGE),--text-change "$(TEXT_CHANGE)")
BIGCLONEBENCH_SELECTION = $(if $(filter 1 yes true,$(KNOWN_FALSE_POSITIVES))$(filter known-false-positive,$(CLONE_TYPE)),--known-false-positives,--clone-type "$(CLONE_TYPE)")

.PHONY: help configure build test test-unit test-repository-analysis test-xml test-source test-policy benchmark-repo benchmark-repos history-scaling history-results bigclonebench-preflight bigclonebench-compile bigclonebench-conflicts bigclonebench-select bigclonebench-snapshot bigclonebench-suite bigclonebench-cases bigclonebench

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
	@printf '  %-28s %s\n' 'make bigclonebench-compile' 'Compile or reuse the local BigCloneBench catalog'
	@printf '  %-28s %s\n' 'make bigclonebench-conflicts' 'Explain content identities excluded for conflicting labels'
	@printf '  %-28s %s\n' 'make bigclonebench-select' 'Publish a selection from the compiled catalog'
	@printf '  %-28s %s\n' 'make bigclonebench-snapshot' 'Materialize an immutable compiled-selection snapshot'
	@printf '  %-28s %s\n' 'make bigclonebench-suite' 'Run Type 1, Type 2, and known-false-positive pair sets'
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

bigclonebench-compile:
	@$(PYTHON) benchmarks/bigclonebench/compile.py \
		--data-root "$(BIGCLONEBENCH_DATA_ROOT)" compile \
		$(if $(COMPILE_LIMIT),--limit-per-kind "$(COMPILE_LIMIT)")

bigclonebench-conflicts:
	@$(PYTHON) benchmarks/bigclonebench/conflicts.py \
		$(if $(BIGCLONEBENCH_DATASET),"$(BIGCLONEBENCH_DATASET)") \
		--data-root "$(BIGCLONEBENCH_DATA_ROOT)" \
		$(if $(CONFLICT_LIMIT),--limit "$(CONFLICT_LIMIT)")

bigclonebench-select:
	@test -n "$(BIGCLONEBENCH_DATASET)" || { echo 'error: BIGCLONEBENCH_DATASET is required'; exit 2; }
	@$(PYTHON) benchmarks/bigclonebench/selection.py "$(BIGCLONEBENCH_DATASET)" \
		--data-root "$(BIGCLONEBENCH_DATA_ROOT)" \
		--pair-set "$(CLONE_TYPE)" --mode "$(MODE)" \
		--role "$(SELECTION_ROLE)" --seed "$(SEED)" \
		--sample-size "$(SAMPLE_SIZE)" \
		$(if $(DEDUPE),--dedupe "$(DEDUPE)")

bigclonebench-snapshot:
	@test -n "$(BIGCLONEBENCH_SELECTION_ID)" || { echo 'error: BIGCLONEBENCH_SELECTION_ID is required'; exit 2; }
	@$(PYTHON) benchmarks/bigclonebench/snapshot.py "$(BIGCLONEBENCH_SELECTION_ID)" \
		--data-root "$(BIGCLONEBENCH_DATA_ROOT)"

bigclonebench-suite:
	@$(PYTHON) benchmarks/bigclonebench/suite.py \
		--data-root "$(BIGCLONEBENCH_DATA_ROOT)" \
		--mode "$(MODE)" --role "$(ROLE)" --seed "$(SEED)" \
		--sample-size "$(SAMPLE_SIZE)" \
		$(if $(filter 1 yes true,$(VERIFY_SOURCE)),--verify-source) \
		--srcdiff /workspace/srcDiff/build/bin/srcdiff \
		--srcmove /workspace/srcMove/build/srcMove

bigclonebench-cases:
	@$(PYTHON) benchmarks/bigclonebench/pipeline.py cases \
		$(BIGCLONEBENCH_SELECTION) --limit "$(LIMIT)" \
		--selection-role "$(SELECTION_ROLE)" $(BIGCLONEBENCH_CASE_OPTIONS) \
		--out-dir "$(CASES_DIR)"

bigclonebench: bigclonebench-cases
	@$(PYTHON) benchmarks/bigclonebench/pipeline.py benchmark \
		$(BIGCLONEBENCH_SELECTION) --cases-dir "$(CASES_DIR)" \
		--srcdiff /workspace/srcDiff/build/bin/srcdiff \
		--srcmove /workspace/srcMove/build/srcMove
