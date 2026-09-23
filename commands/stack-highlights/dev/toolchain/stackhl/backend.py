"""PDF library import (PyMuPDF, with the older "fitz" name as fallback).

Part of stack-highlights; code moved here unchanged from the original single file.
"""

try:
    import pymupdf
except ImportError:  # older package name
    import fitz as pymupdf
