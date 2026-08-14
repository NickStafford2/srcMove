PYTHON ?= python3
CMAKE ?= cmake

.PHONY: help configure build test test-unit test-xml test-source

help:
	@printf '%s\n' 'Available targets:'
	@printf '  %-18s %s\n' 'make build' 'Configure and build srcMove'
	@printf '  %-18s %s\n' 'make test' 'Build and run every correctness suite'
	@printf '  %-18s %s\n' 'make test-unit' 'Run Python infrastructure tests'
	@printf '  %-18s %s\n' 'make test-xml' 'Build and run XML regression tests'
	@printf '  %-18s %s\n' 'make test-source' 'Build and run source-pair regression tests'

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
