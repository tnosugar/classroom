#!/usr/bin/env python3
"""Rebuild this timeline-mcq quiz's HTML from spec.yaml.

Usage:
    python3 make.py
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
for _p in [_here, *_here.parents]:
    if (_p / "shared" / "python" / "timeline_mcq_quiz.py").exists():
        sys.path.insert(0, str(_p / "shared" / "python"))
        break
else:
    raise SystemExit("Could not find classroom/shared/python/timeline_mcq_quiz.py")

from timeline_mcq_quiz import load_spec, render_html


def main():
    spec_path = _here / "spec.yaml"
    spec = load_spec(spec_path)
    events = spec["events"]
    mcq_count = sum(len(e.get("follow_up") or []) for e in events)
    print(f"Loaded {len(events)} events + {mcq_count} MCQ questions from {spec_path.name}")

    out_html = _here / "index.html"
    render_html(spec, out_html)
    print(f"  wrote {out_html.name}  ({out_html.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
