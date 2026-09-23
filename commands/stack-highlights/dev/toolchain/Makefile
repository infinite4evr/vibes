# stack-highlights test harness
#
#   make test      everything: unit tests + golden files + real-book coverage
#                  (coverage needs the books; it is skipped, with a message,
#                  when they are not found -- see tests/run_coverage.py)
#   make quick     unit tests + golden files only (a few seconds, no books needed)
#   make units     unit tests only
#   make golden    golden-file checks only (each also checks its coverage numbers
#                  and its "Check in book" list)
#   make coverage  real-book coverage only (about 1.5 minutes for the six books)
#
#   make update           regenerate golden files -- DELIBERATELY; then review
#                         the diff of tests/golden before keeping it
#   make update-coverage  record the current real-book results as the baseline --
#                         only after checking that any change is an improvement
#   make fixtures         rebuild the fixture PDFs (tests/build_fixtures.py)
#   make clean            remove scratch output and Python caches
#
# `make test` must stay green. A red golden means an edit changed the output
# of the pipeline; if the change was intended, `make update` and review the
# diff, otherwise fix the regression. Coverage failures are never "intended":
# a highlight that is no longer placed is a regression.
#
# Where the books are: $HIGHLIGHT_PDFS, else ../source-pdfs (full-package layout).

PY := python3

.PHONY: test quick units golden coverage update update-coverage fixtures clean

test: units golden coverage

quick: units golden

units:
	@$(PY) tests/test_units.py

golden:
	@$(PY) tests/run_golden.py

coverage:
	@$(PY) tests/run_coverage.py

update:
	@$(PY) tests/run_golden.py --update

update-coverage:
	@$(PY) tests/run_coverage.py --update

fixtures:
	@$(PY) tests/build_fixtures.py

clean:
	@rm -rf tests/.tmp tests/__pycache__ __pycache__ stackhl/__pycache__ tests/fixtures/*.md
	@echo "cleaned scratch output"
