"""Grid-search COVERAGE_FLOOR and DISTINCT_CEILING against recorded answers.

Read-only. Runs form_concepts in memory and persists nothing, so a grid point
costs seconds rather than a full build of 54.

The four hard constraints are the recorded calibration answers in
tests/test_concept_acceptance.py. A point failing any one is rejected outright,
however well it scores elsewhere: those answers were reasoned one cluster at a
time and they outrank any aggregate.
"""
import importlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

import concept_evidence
from utils import DB_PATH

build = importlib.import_module("54_build_concepts")

COVERAGES = (0.3, 0.4, 0.5, 0.6, 0.7)
CEILINGS = (5, 10, 20, 40, 80)


def constraints_hold(score):
    """The four recorded answers. All must hold."""
    return (score["hiwi_concepts"] >= 6
            and not score["hia_joined"]
            and score["himoemoe_sources"] >= 4
            and score["hoi_soy_sources"] == 1)


def _concepts_for(views, index, keys):
    out = {}
    for key in keys:
        if key in views:
            out[key] = build.form_concepts(views[key], index)
    return out


def score_point(views, index):
    """The scoreboard for the thresholds currently set on concept_evidence."""
    got = _concepts_for(views, index, ("hiwi", "hia", "himoemoe", "hoi"))

    hiwi = len(got.get("hiwi", []))

    hia_joined = False
    for c in got.get("hia", []):
        hws = {m["view"]["headword"].lower() for m in c["members"]}
        if {"hia", "hīa"} <= hws:
            hia_joined = True

    himoemoe = max((len({m["view"]["source_id"] for m in c["members"]})
                    for c in got.get("himoemoe", [])), default=0)

    soy = 1
    for c in got.get("hoi", []):
        if any(m["view"]["source_id"] == "paekupu"
               and m["view"]["source_entry_id"] == "hoi" for m in c["members"]):
            soy = len({m["view"]["source_id"] for m in c["members"]})

    return {"hiwi_concepts": hiwi, "hia_joined": hia_joined,
            "himoemoe_sources": himoemoe, "hoi_soy_sources": soy}


def corpus_effects(views, index):
    """Total concepts and the tier split, so a point's cost is visible."""
    tiers = {"certain": 0, "probable": 0, "uncertain": 0}
    total = 0
    for key in views:
        for c in build.form_concepts(views[key], index):
            total += 1
            tiers[c["confidence"]] += 1
    return total, tiers


def main():
    con = sqlite3.connect(DB_PATH)
    views = build.load_senses(con)
    index = concept_evidence.GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
    print(f"gloss index: {len(index):,} glosses\n")

    print(f"{'cov':>5} {'ceil':>5} {'hiwi':>5} {'hia':>5} {'himo':>5} "
          f"{'soy':>4} {'ok':>3} {'concepts':>9} {'ships':>8}")
    for cov in COVERAGES:
        for ceil in CEILINGS:
            concept_evidence.COVERAGE_FLOOR = cov
            concept_evidence.DISTINCT_CEILING = ceil
            s = score_point(views, index)
            ok = constraints_hold(s)
            total, tiers = corpus_effects(views, index)
            ships = tiers["certain"] + tiers["probable"]
            print(f"{cov:>5} {ceil:>5} {s['hiwi_concepts']:>5} "
                  f"{str(s['hia_joined']):>5} {s['himoemoe_sources']:>5} "
                  f"{s['hoi_soy_sources']:>4} {'OK' if ok else 'no':>3} "
                  f"{total:>9,} {ships:>8,}")
    con.close()


if __name__ == "__main__":
    main()
