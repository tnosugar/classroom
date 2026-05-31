#!/usr/bin/env python3
"""Rebuild this quiz's HTML and PDF outputs from spec.yaml.

Usage:
    python3 make.py

Outputs (in this folder, overwritten on each run):
    index.html       — interactive HTML quiz (open in browser)
    radna.pdf        — student worksheet (printable)
    resenja.pdf      — answer key (printable)
"""
import pathlib
import sys

# Locate classroom/shared/python by walking up from this file.
_here = pathlib.Path(__file__).resolve().parent
for _p in [_here, *_here.parents]:
    if (_p / "shared" / "python" / "labeled_location_quiz.py").exists():
        sys.path.insert(0, str(_p / "shared" / "python"))
        break
else:
    raise SystemExit("Could not find classroom/shared/python/ — is this file inside the classroom repo?")

from labeled_location_quiz import load_spec, render_html, render_pdf


def main():
    spec_path = _here / "spec.yaml"
    spec = load_spec(spec_path)
    print(f"Loaded {len(spec['terms'])} terms from {spec_path.name}")

    out_html = _here / "index.html"
    out_pdf_quiz = _here / "radna.pdf"
    out_pdf_answer = _here / "resenja.pdf"

    render_html(spec, out_html)
    print(f"  wrote {out_html.name}  ({out_html.stat().st_size // 1024} KB)")
    render_pdf(spec, out_pdf_quiz, answer=False)
    print(f"  wrote {out_pdf_quiz.name}  ({out_pdf_quiz.stat().st_size // 1024} KB)")
    render_pdf(spec, out_pdf_answer, answer=True)
    print(f"  wrote {out_pdf_answer.name}  ({out_pdf_answer.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
