# stack-highlights test harness
#
#   make test      everything: unit tests + golden files + real-book coverage
#                  + PDF safety (coverage needs Test-Merged-All.pdf; it is
#                  skipped, with a message, when not found -- see tests/run_coverage.py)
#   make quick     unit tests + golden files only (a few seconds, no books needed)
#   make units     unit tests only
#   make golden    golden-file checks only (each also checks its coverage numbers
#                  and its "Check in book" list)
#   make coverage  real-book coverage only: Test-Merged-All.pdf split into its
#                  14 books, each run on its own (3-4 minutes; the first run also
#                  splits the PDF, about 1.5 minutes more)
#   make visual    the 500-page visual test (dev/visual-tests-500): every highlight
#                  on 500 pages was judged by eye; fails if one judged correct is
#                  no longer placed, lists pages whose notes changed (3-4 minutes;
#                  needs dev/ and the PDF, skipped otherwise)
#   make visual-pytest  the same as 500 pytest cases (needs pytest)
#   make pdf-safety  the PDF step (md-to-pdf, recall-sheet, notes-recall):
#                  characters LaTeX cannot handle must never stop a run (about a
#                  minute; skipped, with a message, without pandoc/LaTeX or the tools)
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
# Where the test PDF is: $HIGHLIGHT_PDFS/Test-Merged-All.pdf, else
# dev/source-pdfs/Test-Merged-All.pdf (the development archive kept next to this
# file; see README.md).

PY := python3
HIGHLIGHT_PDFS ?= $(CURDIR)/dev/source-pdfs
export HIGHLIGHT_PDFS

.PHONY: test quick units golden coverage visual visual-pytest pdf-safety update update-coverage fixtures clean

test: units golden coverage pdf-safety

quick: units golden

units:
	@$(PY) tests/test_units.py

golden:
	@$(PY) tests/run_golden.py

coverage:
	@$(PY) tests/run_coverage.py

visual:
	@if [ -f dev/visual-tests-500/run_visual_tests.py ]; then $(PY) dev/visual-tests-500/run_visual_tests.py; \
	 else echo "SKIP visual test: dev/visual-tests-500 not found (it is part of the dev/ archive)"; fi

visual-pytest:
	@if [ -f dev/visual-tests-500/test_visual_500.py ]; then $(PY) -m pytest -q dev/visual-tests-500/test_visual_500.py; \
	 else echo "SKIP visual test: dev/visual-tests-500 not found (it is part of the dev/ archive)"; fi

pdf-safety:
	@$(PY) tests/test_pdf_safety.py

update:
	@$(PY) tests/run_golden.py --update

update-coverage:
	@$(PY) tests/run_coverage.py --update

fixtures:
	@$(PY) tests/build_fixtures.py

clean:
	@rm -rf tests/.tmp tests/__pycache__ __pycache__ stackhl/__pycache__ tests/fixtures/*.md \
	        dev/visual-tests-500/__pycache__ dev/visual-tests-500/.pytest_cache .pytest_cache
	@echo "cleaned scratch output"
