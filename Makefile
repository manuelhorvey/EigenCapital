.PHONY: install install-dev test lint run retrain retrain-schedule deps snapshot clean

install:
	uv pip sync requirements.lock

install-dev:
	uv pip sync requirements.lock requirements-dev.lock

test:
	python -m pytest tests/ -v $(ARGS)

test-cov:
	python -m pytest tests/ --cov=. --cov-report=term-missing -v

lint:
	python -m py_compile paper_trading/engine.py paper_trading/serve.py paper_trading/ops/monitor.py
	python -m py_compile features/labels.py risk/position_sizing.py monitoring/validity_state_machine.py

run:
	PYTHONPATH=$$PYTHONPATH:. python -m paper_trading.ops.monitor

# ── Retrain pipeline ────────────────────────────────────────────────────────

retrain:
	PYTHONPATH=$$PYTHONPATH:. python scripts/training/pipeline.py

retrain-fast:
	PYTHONPATH=$$PYTHONPATH:. python scripts/training/pipeline.py --retrain-only

retrain-schedule:
	./scripts/ops/retrain_scheduler.sh

retrain-schedule-dry:
	./scripts/ops/retrain_scheduler.sh --dry-run

# ── Systemd retrain timer (user-level) ──────────────────────────────────────

retrain-install:
	@echo "Installing systemd retrain timer..."
	@mkdir -p ~/.config/systemd/user
	@cp ops/eigencapital-retrain.service ~/.config/systemd/user/eigencapital-retrain.service
	@cp ops/eigencapital-retrain.timer ~/.config/systemd/user/eigencapital-retrain.timer
	@systemctl --user daemon-reload
	@systemctl --user enable eigencapital-retrain.timer
	@systemctl --user start eigencapital-retrain.timer
	@echo "Retrain timer installed and started. Status:"
	@systemctl --user status eigencapital-retrain.timer --no-pager

retrain-uninstall:
	@echo "Removing systemd retrain timer..."
	-systemctl --user stop eigencapital-retrain.timer 2>/dev/null || true
	-systemctl --user disable eigencapital-retrain.timer 2>/dev/null || true
	@rm -f ~/.config/systemd/user/eigencapital-retrain.service
	@rm -f ~/.config/systemd/user/eigencapital-retrain.timer
	@systemctl --user daemon-reload
	@echo "Retrain timer removed."

retrain-status:
	@echo "Retrain timer status:"
	-systemctl --user status eigencapital-retrain.timer --no-pager 2>/dev/null || echo "  (not installed)"
	@echo ""
	@echo "Recent retrain logs:"
	@ls -lt data/logs/retrain/ 2>/dev/null | head -5 || echo "  (none)"

# ── Health check ─────────────────────────────────────────────────────────────

health-check:
	PYTHONPATH=$$PYTHONPATH:. python scripts/ops/model_health_monitor.py

health-check-json:
	PYTHONPATH=$$PYTHONPATH:. python scripts/ops/model_health_monitor.py --json

health-check-trigger:
	PYTHONPATH=$$PYTHONPATH:. python scripts/ops/model_health_monitor.py --trigger

health-check-install:
	@echo "Installing systemd health-check timer..."
	@mkdir -p ~/.config/systemd/user
	@cp ops/eigencapital-healthcheck.service ~/.config/systemd/user/eigencapital-healthcheck.service
	@cp ops/eigencapital-healthcheck.timer ~/.config/systemd/user/eigencapital-healthcheck.timer
	@systemctl --user daemon-reload
	@systemctl --user enable eigencapital-healthcheck.timer
	@systemctl --user start eigencapital-healthcheck.timer
	@echo "Health-check timer installed and started. Status:"
	@systemctl --user status eigencapital-healthcheck.timer --no-pager

health-check-uninstall:
	@echo "Removing systemd health-check timer..."
	-systemctl --user stop eigencapital-healthcheck.timer 2>/dev/null || true
	-systemctl --user disable eigencapital-healthcheck.timer 2>/dev/null || true
	@rm -f ~/.config/systemd/user/eigencapital-healthcheck.service
	@rm -f ~/.config/systemd/user/eigencapital-healthcheck.timer
	@systemctl --user daemon-reload
	@echo "Health-check timer removed."

health-check-status:
	@echo "Health-check timer status:"
	-systemctl --user status eigencapital-healthcheck.timer --no-pager 2>/dev/null || echo "  (not installed)"
	@echo ""
	@echo "Latest health report:"
	@cat data/logs/healthcheck/latest.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  (no report yet)"

# ── Combined install ─────────────────────────────────────────────────────────

all-timers-install: retrain-install health-check-install
	@echo ""
	@echo "All timers installed:"
	-systemctl --user list-timers --no-pager 2>/dev/null | grep eigencapital || true

all-timers-uninstall: retrain-uninstall health-check-uninstall
	@echo "All timers removed."

deps:
	uv pip compile requirements.in --output-file requirements.lock
	uv pip compile requirements-dev.in --output-file requirements-dev.lock

snapshot:
	python scripts/generate_snapshot.py

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
