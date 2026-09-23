# stack-highlights test harness
#
#   make test     run unit tests + golden-file checks (the safety net)
#   make units    unit tests only (fast)
#   make golden   golden-file checks only
#   make update   regenerate golden files -- do this DELIBERATELY, then
#                 eyeball `git diff tests/golden` before committing
#   make clean    remove scratch output
#
# `make test` must stay green. A red golden means an edit changed the output
# of the pipeline; if the change was intended, `make update` and review the
# diff, otherwise fix the regression.

PY := python3

.PHONY: test units golden update clean

test: units golden

units:
	@$(PY) tests/test_units.py

golden:
	@$(PY) tests/run_golden.py

update:
	@$(PY) tests/run_golden.py --update

clean:
	@rm -rf tests/.tmp tests/__pycache__ __pycache__ tests/fixtures/*.md
	@echo "cleaned scratch output"
