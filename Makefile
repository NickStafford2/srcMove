PYTHON ?= python3
CMAKE ?= cmake
CLONE_TYPE ?= type1
SELECTION_ROLE ?= tuning
BENCHMARK_CACHE_ROOT ?= bigMoveBench/cache
BENCHMARK_RESULTS_ROOT ?= benchmark-results
BIGCLONEBENCH_DATASET ?=
BIGCLONEBENCH_SELECTION_ID ?=
MODE ?= sample
PROFILE ?= small
SEED ?= 0
SAMPLE_SIZE ?= 100
ROLE ?= tuning
VERIFY_SOURCE ?= 0
.PHONY: help configure build test test-unit test-bigmovebench test-performance test-srcmove-history test-xml test-source test-policy test-classification history-scaling bigmovebench-preflight bigmovebench-compile bigmovebench-conflicts bigmovebench-select bigmovebench-benchmark-cases bigmovebench-snapshot bigmovebench-suite

help:
	@printf '%s\n' 'Available targets:'
	@printf '  %-28s %s\n' 'make build' 'Configure and build srcMove'
	@printf '  %-28s %s\n' 'make test' 'Build and run every correctness suite'
	@printf '  %-28s %s\n' 'make test-unit' 'Run all Python unit tests'
	@printf '  %-28s %s\n' 'make test-bigmovebench' 'Run focused BigMoveBench unit tests'
	@printf '  %-28s %s\n' 'make test-performance' 'Run performance workload runner unit tests'
	@printf '  %-28s %s\n' 'make test-srcmove-history' 'Run srcmove-history unit tests'
	@printf '  %-28s %s\n' 'make test-xml' 'Build and run XML regression tests'
	@printf '  %-28s %s\n' 'make test-source' 'Build and run source-pair regression tests'
	@printf '  %-28s %s\n' 'make test-policy' 'Build and run reviewer-editable move-policy tests'
	@printf '  %-28s %s\n' 'make test-classification' 'Run the focused Type-1/2/3/none contracts'
	@printf '  %-28s %s\n' 'make history-scaling' 'Measure history throughput across JOBS'
	@printf '  %-28s %s\n' 'make bigmovebench-preflight' 'Check the local BigCloneBench installation'
	@printf '  %-28s %s\n' 'make bigmovebench-compile' 'Compile or reuse the local BigCloneBench catalog'
	@printf '  %-28s %s\n' 'make bigmovebench-conflicts' 'Explain content identities excluded for conflicting labels'
	@printf '  %-28s %s\n' 'make bigmovebench-select' 'Publish a selection from the compiled catalog'
	@printf '  %-28s %s\n' 'make bigmovebench-benchmark-cases' 'Publish normalized cases from a selection'
	@printf '  %-28s %s\n' 'make bigmovebench-snapshot' 'Materialize an immutable compiled-selection snapshot'
	@printf '  %-28s %s\n' 'make bigmovebench-suite' 'Run BigMoveBench PROFILE=small|medium (full is slow)'

configure:
	$(CMAKE) -S . -B build -G Ninja

build: configure
	$(CMAKE) --build build

test: build
	$(PYTHON) tests/run.py

test-unit:
	$(PYTHON) tests/run.py --suite unit --suite bigmovebench --suite performance

test-bigmovebench:
	$(PYTHON) tests/run.py --suite bigmovebench

test-performance:
	$(PYTHON) tests/run.py --suite performance

test-srcmove-history:
	$(PYTHON) tests/run.py --suite srcmove-history

test-xml: build
	$(PYTHON) tests/run.py --suite xml

test-source: build
	$(PYTHON) tests/run.py --suite source

test-policy: build
	$(PYTHON) tests/run.py --suite policy

test-classification: build
	$(PYTHON) tests/run.py --suite policy \
		--case classification_type1_java_method_whitespace \
		--case classification_type1_java_method_comments \
		--case classification_type2_java_method_identifiers \
		--case classification_type2_java_method_literal \
		--case classification_type2_java_method_identifiers_and_literal \
		--case classification_type3_java_method_added_statement \
		--case classification_type3_java_method_removed_statement \
		--case classification_type3_java_method_modified_statement \
		--case classification_type3_java_method_inconsistent_renaming \
		--case classification_none_unrelated_java_methods \
		--case classification_none_similar_java_method_shapes

history-scaling:
	@test -n "$(CASE)" || { echo 'error: CASE is required'; exit 2; }
	@test -n "$(START)" || { echo 'error: START is required'; exit 2; }
	@test -n "$(COUNT)" || { echo 'error: COUNT is required'; exit 2; }
	@test -n "$(JOBS)" || { echo 'error: JOBS is required'; exit 2; }
	@$(PYTHON) srcmove_history/benchmarks/scaling.py "$(CASE)" \
		--start "$(START)" --count "$(COUNT)" --jobs "$(JOBS)" \
		$(if $(REPETITIONS),--repetitions "$(REPETITIONS)") \
		$(if $(WARMUPS),--warmups "$(WARMUPS)") \
		$(if $(SEED),--seed "$(SEED)") \
		$(if $(LABEL),--label "$(LABEL)") \
		$(if $(ENVIRONMENT_LABEL),--environment-label "$(ENVIRONMENT_LABEL)") \
		--results-root "$(BENCHMARK_RESULTS_ROOT)" \
		$(if $(SCRATCH_ROOT),--scratch-root "$(SCRATCH_ROOT)") \
		$(if $(DIRECTORY),--directory "$(DIRECTORY)") \
		$(if $(filter 1 yes true,$(UPDATE)),--fetch) \
		$(if $(filter 1 yes true,$(OFFLINE)),--offline)

bigmovebench-preflight:
	@$(PYTHON) bigMoveBench/installation.py

bigmovebench-compile:
	@$(PYTHON) bigMoveBench/compile.py \
		--cache-root "$(BENCHMARK_CACHE_ROOT)" compile \
		$(if $(COMPILE_LIMIT),--limit-per-kind "$(COMPILE_LIMIT)")

bigmovebench-conflicts:
	@$(PYTHON) bigMoveBench/conflicts.py \
		$(if $(BIGCLONEBENCH_DATASET),"$(BIGCLONEBENCH_DATASET)") \
		--cache-root "$(BENCHMARK_CACHE_ROOT)" \
		$(if $(CONFLICT_LIMIT),--limit "$(CONFLICT_LIMIT)")

bigmovebench-select:
	@test -n "$(BIGCLONEBENCH_DATASET)" || { echo 'error: BIGCLONEBENCH_DATASET is required'; exit 2; }
	@$(PYTHON) bigMoveBench/selection.py "$(BIGCLONEBENCH_DATASET)" \
		--cache-root "$(BENCHMARK_CACHE_ROOT)" \
		--pair-set "$(CLONE_TYPE)" --mode "$(MODE)" \
		--role "$(SELECTION_ROLE)" --seed "$(SEED)" \
		--sample-size "$(SAMPLE_SIZE)" \
		$(if $(DEDUPE),--dedupe "$(DEDUPE)")

bigmovebench-benchmark-cases:
	@test -n "$(BIGCLONEBENCH_SELECTION_ID)" || { echo 'error: BIGCLONEBENCH_SELECTION_ID is required'; exit 2; }
	@$(PYTHON) bigMoveBench/benchmark_cases.py "$(BIGCLONEBENCH_SELECTION_ID)" \
		--cache-root "$(BENCHMARK_CACHE_ROOT)"

bigmovebench-snapshot:
	@test -n "$(BIGCLONEBENCH_SELECTION_ID)" || { echo 'error: BIGCLONEBENCH_SELECTION_ID is required'; exit 2; }
	@$(PYTHON) bigMoveBench/snapshot.py "$(BIGCLONEBENCH_SELECTION_ID)" \
		--cache-root "$(BENCHMARK_CACHE_ROOT)"

bigmovebench-suite:
	@$(PYTHON) bigMoveBench/suite.py \
		--cache-root "$(BENCHMARK_CACHE_ROOT)" \
		--results-root "$(BENCHMARK_RESULTS_ROOT)" \
		--profile "$(PROFILE)" --role "$(ROLE)" \
		$(if $(PAIR_SET),--pair-set "$(PAIR_SET)") \
		$(if $(filter 1 yes true,$(VERIFY_SOURCE)),--verify-source) \
		--srcdiff /workspace/srcDiff/build/bin/srcdiff \
		--srcmove /workspace/srcMove/build/srcMove
