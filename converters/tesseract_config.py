"""Ensure pytesseract and img2table can find the Tesseract binary on Windows.

The winget-installed Tesseract puts tesseract.exe under the user's
Local\\Programs directory, which is often not on PATH for subprocesses
launched from inside the web server. We set both pytesseract's explicit
command path AND prepend the install dir to PATH (img2table's TesseractOCR
shells out to the bare `tesseract` command, so it needs PATH).
"""

import os
import shutil
from pathlib import Path

import pytesseract

_CANDIDATES = [
    Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
]


def configure() -> None:
    found = shutil.which("tesseract")
    if found:
        return
    for candidate in _CANDIDATES:
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            # Put the install dir on PATH so img2table (which calls the bare
            # `tesseract` command) can find it too.
            tess_dir = str(candidate.parent)
            if tess_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = tess_dir + os.pathsep + os.environ.get("PATH", "")
            return


configure()
