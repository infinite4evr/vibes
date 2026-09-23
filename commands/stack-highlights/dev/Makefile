# Development archive: run from stack-highlights/dev.
# Every test target runs the live toolchain one folder up (make -C ..), on
# source-pdfs/Test-Merged-All.pdf.

PY := python3
export HIGHLIGHT_PDFS := $(CURDIR)/source-pdfs

.PHONY: test quick coverage visual visual-pytest verify

# unit tests + golden files + real-book coverage + PDF safety (about 5 minutes)
test:
	@$(MAKE) --no-print-directory -C .. test

# unit tests + golden files only (seconds)
quick:
	@$(MAKE) --no-print-directory -C .. quick

# real-book coverage only (14 books of the merged PDF, 3-4 minutes)
coverage:
	@$(MAKE) --no-print-directory -C .. coverage

# the 500-page visual test (3-4 minutes)
visual:
	@$(MAKE) --no-print-directory -C .. visual

visual-pytest:
	@$(MAKE) --no-print-directory -C .. visual-pytest

# files, counts and checksums of this archive (add --pdf to check the merged PDF too)
verify:
	@$(PY) verify_package.py
