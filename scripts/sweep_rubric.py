"""The sweep rubric's version, and the link between the document and the code.

The rubric itself is prose — `docs/SWEEP_RUBRIC.md` — because it is a standard
for judgement, not a config. What lives here is the version string that gets
stamped onto every finding and every completed cluster, so a change to the
standard can be turned into a targeted re-sweep rather than a silent
inconsistency between the corpus's early and late halves.

Bump VERSION and the document's heading together. The test suite fails if they
disagree, and fails if the document stops describing a finding kind the code
still accepts — the two drifting apart is how a rubric quietly stops being the
thing the sweep is actually applying.
"""
import re
from pathlib import Path

VERSION = "v1"

RUBRIC_PATH = Path(__file__).parent.parent / "docs" / "SWEEP_RUBRIC.md"

_HEADING_RE = re.compile(r"^#\s*Audit Sweep Rubric\s*—\s*(v\d+)\s*$", re.M)
_KIND_RE = re.compile(r"^###\s+`([a-z_]+)`\s*$", re.M)


def read_rubric() -> str:
    return RUBRIC_PATH.read_text(encoding="utf-8")


def documented_version(text: str | None = None) -> str | None:
    """The version the document declares in its heading."""
    m = _HEADING_RE.search(text if text is not None else read_rubric())
    return m.group(1) if m else None


def documented_kinds(text: str | None = None) -> set:
    """The finding kinds the document defines a section for."""
    return set(_KIND_RE.findall(text if text is not None else read_rubric()))
