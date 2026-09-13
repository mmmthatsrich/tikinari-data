"""Grid-search COVERAGE_FLOOR and DISTINCT_CEILING against recorded answers.

Read-only. Runs form_concepts in memory and persists nothing, so a grid point
costs seconds rather than a full build of 54.

The four hard constraints are the recorded calibration answers in
tests/test_concept_acceptance.py. A point failing any one is rejected outright,
however well it scores elsewhere: those answers were reasoned one cluster at a
time and they outrank any aggregate.

A fifth criterion joins them, because the first grid run showed the four cannot
discriminate on their own: the thresholds never change grouping (see
score_point), so all four answers hold identically at every point. What the
thresholds change is the TIER, and a recorded-correct grouping tiered
'uncertain' is withheld by 60_export_app_db — the answer is right in staging
and denied in practice. So a recorded-correct cluster must also SHIP.

Selection is then for the TIGHTEST point that satisfies everything, not the
loosest: highest COVERAGE_FLOOR, and on a tie the lowest DISTINCT_CEILING.
A wrong merge shows two different words as one and misinforms about the
language; a missed merge shows a user two entries where one would do, which is
what every existing dictionary already does, and concepts are a pure overlay so
every sense reaches the app either way.
"""
import importlib
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

import concept_evidence
from utils import DB_PATH

build = importlib.import_module("54_build_concepts")

COVERAGES = (0.3, 0.4, 0.5, 0.6, 0.7)
CEILINGS = (5, 10, 20, 40, 80)

# A cap on the coverage axis that the corpus cannot supply and the design can.
# Section 2 of the design lists hoatu 'Give' / 'Give forth.' at coverage 0.50
# as CORRECT, one of the two rows the coverage axis exists to rescue, and
# huripari sits on the same 0.50. A floor above this grades both weak, which
# would put the thresholds in contradiction with the document they implement.
# Every criterion below is silent on the floor — himoemoe is rescued by df,
# not by coverage — so without this the tightest-satisfying rule would run the
# floor up to the tight edge of whatever grid it was handed. Pinned by
# GlossGrading.test_the_specs_own_half_coverage_example_is_ordinary_evidence;
# raising it means revisiting section 2 first.
SPEC_COVERAGE_CAP = 0.5


def constraints_hold(score):
    """The four recorded answers. All must hold."""
    return (score["hiwi_concepts"] >= 6
            and not score["hia_joined"]
            and score["himoemoe_sources"] >= 4
            and score["hoi_soy_sources"] == 1)


def clusters_reach_users(score):
    """The fifth criterion: a recorded-correct grouping must SHIP.

    himoemoe only. The other three recorded answers are answers about
    SEPARATION — hiwi is eight words and not one, hia is not hīa,
    paekupu:hoi 'soy' stands alone — and demanding that every fragment of a
    separation answer also ships would assert something no reviewer ever
    recorded. himoemoe's answer is the opposite kind: one word, six sources
    across the key, no disagreement anywhere. Tiering that 'uncertain' means
    filter_concepts() withholds it and the answer never reaches a user, so
    the threshold has denied it as surely as fragmenting it would have.

    Keyed on the SHIPPING concepts' source count against the same >=4 the
    acceptance test records, so the criterion is the recorded answer itself
    rather than a second, softer version of it. >=4 and not 6 because the
    corpus does not in fact produce a single six-source concept here: it
    produces two, {hepatakakupu, te_aka, te_matatiki, williams} and
    {kimikupu_hou, paekupu}, at every point on the grid. hepatakakupu's
    gloss_en is NULL and it seeds first, so that split is not a gloss-grading
    outcome and no threshold closes it.

    Kept apart from constraints_hold deliberately: those four are about
    grouping and this one is about tiering, and a grid where the first four
    hold everywhere is exactly when the difference matters.
    """
    return score["himoemoe_shipping_sources"] >= 4


def point_is_acceptable(score):
    """Every criterion. Shipping is additional to the four, never instead."""
    return constraints_hold(score) and clusters_reach_users(score)


def _concepts_for(views, index, keys):
    out = {}
    for key in keys:
        if key in views:
            out[key] = build.form_concepts(views[key], index)
    return out


def _max_sources(concepts, shipping=False):
    """Widest source span among these concepts; shipping ones only if asked.

    'Shipping' approximates filter_concepts() as confidence != 'uncertain'.
    That is EXACT ONLY WHILE NO SWEEP JUDGEMENTS EXIST — today all 175,101
    memberships are 'proposed'. Once the sweep starts judging it diverges in
    both directions, and this tuner sees neither:

      - a concept with a confirmed member ships despite an 'uncertain' tier
        (filter_concepts keeps status='confirmed'), so this UNDER-counts;
      - a rejected member is dropped at export, shrinking the source span of
        a concept that does ship, so this OVER-counts its width.

    Both are futures, not bugs today. When judgements exist, this function is
    the thing to fix first — re-tuning against a corpus the sweep has touched
    means asking filter_concepts, not guessing at it.
    """
    return max((len({m["view"]["source_id"] for m in c["members"]})
                for c in concepts
                if not shipping or c["confidence"] != "uncertain"), default=0)


def _n_shipping(concepts):
    return sum(1 for c in concepts if c["confidence"] != "uncertain")


# The soft scoreboard of the design, section 5: the four clusters the
# superseded GLOSS_OVERLAP_MIN comment records specific behaviour for. Soft by
# design — reported, never constrained — but reported HERE rather than only in
# a report, so re-running this script gives the same scoreboard the choice was
# made against. Each is printed as 'concepts/shipping'.
SOFT_CLUSTERS = ("huripari", "hoatu", "huatea", "itinga")


def soft_scoreboard(views, index):
    """{cluster: (n concepts, n shipping)} for the section 5 clusters."""
    got = _concepts_for(views, index, SOFT_CLUSTERS)
    return {k: (len(got.get(k, [])), _n_shipping(got.get(k, [])))
            for k in SOFT_CLUSTERS}


def score_point(views, index):
    """The scoreboard for the thresholds currently set on concept_evidence."""
    got = _concepts_for(views, index, ("hiwi", "hia", "himoemoe", "hoi"))

    hiwi = len(got.get("hiwi", []))

    hia_joined = False
    for c in got.get("hia", []):
        hws = {m["view"]["headword"].lower() for m in c["members"]}
        if {"hia", "hīa"} <= hws:
            hia_joined = True

    himoemoe = _max_sources(got.get("himoemoe", []))
    himoemoe_ships = _max_sources(got.get("himoemoe", []), shipping=True)

    soy = 1
    for c in got.get("hoi", []):
        if any(m["view"]["source_id"] == "paekupu"
               and m["view"]["source_entry_id"] == "hoi" for m in c["members"]):
            soy = len({m["view"]["source_id"] for m in c["members"]})

    return {"hiwi_concepts": hiwi, "hia_joined": hia_joined,
            "himoemoe_sources": himoemoe,
            "himoemoe_shipping_sources": himoemoe_ships,
            "hoi_soy_sources": soy,
            # Reported, not constrained: the separation clusters' shipping
            # rates, so the judgement above about which clusters the fifth
            # criterion covers stays visible and can be revisited.
            "hiwi_shipping": _n_shipping(got.get("hiwi", [])),
            "hia_shipping": _n_shipping(got.get("hia", []))}


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
    """Print the grid. Exits 2 rather than 0 if no point is selectable, so a
    refusal is loud to a wrapper instead of looking like a clean run."""
    # Opened read-only at the driver, not merely by discipline: this script
    # exists to be re-run by whoever re-tunes next, and the one thing it must
    # never do is write to the corpus it is measuring.
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    views = build.load_senses(con)
    index = concept_evidence.GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))

    # Provenance printed rather than hand-added to the saved file afterwards,
    # so a plain redirect reproduces the artifact whole.
    print("$ python scripts/tune_gloss_thresholds.py")
    print(f"# {date.today().isoformat()}, against {DB_PATH.name} opened "
          f"read-only: {len(index):,} glosses,")
    print(f"# {len(views):,} headword keys. form_concepts runs in memory; "
          f"nothing is persisted.")
    print("# 'ships' = certain + probable, what 60_export_app_db lets "
          "through. 'uncert' is what it")
    print("# withholds, which is also the sweep's review queue.\n")

    print("hard      hiwi/hia/himo/soy — the four recorded answers, grouping")
    print("shipping  himo^ is himoemoe's widest SHIPPING source span, and the "
          "fifth criterion")
    print("          wants >= 4; hiwi^/hia^ are reported, not constrained")
    print("soft      the section 5 clusters, concepts/shipping — reported, "
          "never constrained\n")
    head = (f"{'cov':>5} {'ceil':>5} {'hiwi':>5} {'hia':>5} {'himo':>5} "
            f"{'soy':>4} | {'himo^':>5} {'hiwi^':>5} {'hia^':>5} | "
            + " ".join(f"{k[:5]:>7}" for k in SOFT_CLUSTERS)
            + f" | {'ok':>3} {'concepts':>9} {'ships':>8} {'uncert':>7}")
    print(head)
    accepted = []
    for cov in COVERAGES:
        for ceil in CEILINGS:
            concept_evidence.COVERAGE_FLOOR = cov
            concept_evidence.DISTINCT_CEILING = ceil
            s = score_point(views, index)
            soft = soft_scoreboard(views, index)
            ok = point_is_acceptable(s)
            total, tiers = corpus_effects(views, index)
            ships = tiers["certain"] + tiers["probable"]
            if ok:
                accepted.append((cov, ceil, ships, tiers["uncertain"]))
            print(f"{cov:>5} {ceil:>5} {s['hiwi_concepts']:>5} "
                  f"{str(s['hia_joined']):>5} {s['himoemoe_sources']:>5} "
                  f"{s['hoi_soy_sources']:>4} | "
                  f"{s['himoemoe_shipping_sources']:>5} "
                  f"{s['hiwi_shipping']:>5} {s['hia_shipping']:>5} | "
                  + " ".join(f"{f'{n}/{sh}':>7}" for n, sh in
                             (soft[k] for k in SOFT_CLUSTERS))
                  + f" | {'OK' if ok else 'no':>3} "
                    f"{total:>9,} {ships:>8,} {tiers['uncertain']:>7,}")
    con.close()

    # Tightest, not loosest: highest floor, then lowest ceiling. 'ships' is
    # monotone in both axes, so maximising it can only ever name the loose
    # corner of whatever grid was run — it is not a measurement. The owner's
    # recorded preference is that a wrong merge costs more than a missed one,
    # and the criteria above are what stop 'tightest' being just as mechanical
    # a corner-pick in the other direction.
    if not accepted:
        print("\nNO POINT SATISFIES EVERY CRITERION — report this, do not "
              "relax one.")
        sys.exit(2)

    def tightest(points):
        return max(points, key=lambda p: (p[0], -p[1]))

    def show(label, point):
        cov, ceil, ships, uncertain = point
        print(f"{label}: COVERAGE_FLOOR = {cov}, DISTINCT_CEILING = {ceil} "
              f"({ships:,} concepts ship, {uncertain:,} uncertain)")

    print()
    show("tightest satisfying point", tightest(accepted))
    within = [p for p in accepted if p[0] <= SPEC_COVERAGE_CAP]
    if not within:
        print("NO SATISFYING POINT HAS A FLOOR AT OR BELOW THE SPEC CAP "
              f"({SPEC_COVERAGE_CAP}) — report this, do not raise the cap.")
        sys.exit(2)
    show(f"  tightest with floor <= {SPEC_COVERAGE_CAP} (the section 2 cap, "
         "and what is SET)", tightest(within))


if __name__ == "__main__":
    main()
