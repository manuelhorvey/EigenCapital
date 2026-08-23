.PHONY: install dev test test-unit test-property lint typecheck clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install package
	pip install -e .

dev:  ## Install with dev dependencies
	pip install -e ".[dev]"

test:  ## Run all tests
	python -m pytest tests/ -v

test-unit:  ## Run unit tests only
	python -m pytest tests/unit/ -v

test-property:  ## Run property-based tests
	python -m pytest tests/property/ -v

lint:  ## Run linting
	python -m ruff check src/ tests/

typecheck:  ## Run type checking
	python -m mypy src/eigencapital/

clean:  ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
