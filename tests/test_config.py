"""Config invariant tests — guard against accidental scoring/catalog edits."""

import csv
import json
import re
from pathlib import Path

import pytest

from config import (
    DISTANCE_FROM_KABUL_KM,
    LANGUAGE_SIMILARITY,
    NUMERIC_TO_ISO3,
    OPPORTUNITY_SCORE_WEIGHTS,
    PRODUCTS,
    YEARS,
)

HS_CODE_PATTERN = re.compile(r"^\d{6}$")
COUNTRY_CODE_PATTERN = re.compile(r"^\d{1,3}$")

# UN Comtrade's own per-revision HS6 classification references -- the same
# nomenclature Comtrade resolves clCode="HS" queries against, so validating
# PRODUCTS codes here guarantees they're codes the live API actually
# recognises for the years we query.
#
# Comtrade's own revision naming (NOT chronological-sounding -- double
# checked against https://comtradeapi.un.org/files/v1/app/reference/ListofReferences.json):
#   H5 = HS2017 edition, in force 2017-01-01 through 2021-12-31
#   H6 = HS2022 edition, in force 2022-01-01 onward (per WCO's HS2022
#        edition: https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs-nomenclature-2022-edition/hs-nomenclature-2022-edition.aspx)
#
# A handful of codes were added/retired/split at that boundary (e.g. pine
# nuts: 080290 -> 080291/080292), so a code that's valid in one revision can
# be silently wrong for part of YEARS. Each product's code list must
# therefore cover every year in YEARS, not just "exist somewhere".
HS_REFERENCE_FILES = {
    "H5": "hs_h5.json",  # HS2017 -- covers years <= 2021
    "H6": "hs_h6.json",  # HS2022 -- covers years >= 2022
}
HS_REVISION_CUTOVER_YEAR = 2022  # first year classified under HS2022 (H6)


def _load_hs_reference(revision: str) -> dict[str, dict]:
    path = Path(__file__).resolve().parent.parent / "reference" / HS_REFERENCE_FILES[revision]
    with open(path, encoding="utf-8") as f:
        results = json.load(f)["results"]
    return {r["id"]: r for r in results}


def _revision_for_year(year: int) -> str:
    return "H6" if year >= HS_REVISION_CUTOVER_YEAR else "H5"


# WCO/UNSD's official HS2017<->HS2022 correlation table -- tells us exactly
# which codes are successors/predecessors of which across the revision
# boundary (relationship 1:1, 1:n, n:1, n:n), rather than us having to
# manually diff the two nomenclature files by hand.
# Source: https://unstats.un.org/unsd/classifications/Econ/tables/HS2022toHS2017ConversionAndCorrelationTables.xlsx
# (linked from https://unstats.un.org/unsd/classifications/Econ, "Correspondences"
# section; WCO publishes the same table at
# https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs-nomenclature-2022-edition/correlation-tables-hs-2017-2022.aspx)
HS_CORRELATION_PATH = Path(__file__).resolve().parent.parent / "reference" / "hs2017_hs2022_correlation.csv"


def _load_hs_correlation() -> list[dict]:
    with open(HS_CORRELATION_PATH, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestOpportunityScoreWeights:
    def test_weights_sum_to_one(self):
        total = sum(OPPORTUNITY_SCORE_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_all_weights_positive(self):
        assert all(w > 0 for w in OPPORTUNITY_SCORE_WEIGHTS.values())


class TestProducts:
    def test_every_product_has_name_and_codes(self):
        for name, product in PRODUCTS.items():
            assert name.strip()
            assert product.get("codes")
            assert product.get("category", "").strip()
            assert product.get("description", "").strip()

    def test_hs_codes_are_six_digits(self):
        for name, product in PRODUCTS.items():
            for code in product["codes"]:
                assert HS_CODE_PATTERN.match(code), f"{name}: invalid HS code {code!r}"

    def test_hs_codes_exist_in_official_nomenclature(self):
        """Every code must be a real, product-level (leaf) HS6 code in at
        least one HS revision we query -- not a typo or a pure aggregate."""
        references = {rev: _load_hs_reference(rev) for rev in HS_REFERENCE_FILES}
        for name, product in PRODUCTS.items():
            for code in product["codes"]:
                hits = {rev: ref.get(code) for rev, ref in references.items()}
                assert any(hits.values()), (
                    f"{name}: HS code {code!r} does not exist in any HS "
                    f"revision we query ({', '.join(HS_REFERENCE_FILES)})"
                )
                for rev, entry in hits.items():
                    if entry is not None:
                        assert entry["isLeaf"] == "1", (
                            f"{name}: HS code {code!r} is not a product-level "
                            f"code in {rev} (it's a heading/chapter aggregate: "
                            f"{entry['text']!r})"
                        )

    def test_hs_codes_cover_every_query_year(self):
        """For every year in YEARS, at least one of a product's codes must be
        a valid leaf code under the HS revision in force that year -- so a
        revision-boundary split (like pine nuts in 2022) can't silently drop
        a whole year of data."""
        references = {rev: _load_hs_reference(rev) for rev in HS_REFERENCE_FILES}
        revisions_needed = {_revision_for_year(y) for y in YEARS}

        for name, product in PRODUCTS.items():
            for rev in revisions_needed:
                ref = references[rev]
                covered = any(
                    ref.get(code, {}).get("isLeaf") == "1" for code in product["codes"]
                )
                assert covered, (
                    f"{name}: none of {product['codes']} is a valid HS6 code "
                    f"under {rev} -- data for years classified under {rev} "
                    f"will be silently missing"
                )

    def test_hs_code_revision_changes_are_tracked(self):
        """
        Cross-check every code against the WCO/UNSD HS2017<->HS2022
        correlation table. This catches two things the plain existence/
        coverage checks above can't:

          1. A code retired/split at the 2022 cutover, where the product's
             code list is missing the *specific* successor/predecessor the
             table says it needs (a more precise version of the coverage
             check above, with the correlated code named automatically
             instead of found by manually diffing H5 vs H6).
          2. A code that happens to be a valid leaf in both revisions, but
             isn't linked as the same line item in the table -- i.e. the
             6-digit number was freed up and reassigned to something
             unrelated between editions, so "valid in both" would otherwise
             look safe while silently meaning two different products.
        """
        correlation = _load_hs_correlation()
        references = {rev: _load_hs_reference(rev) for rev in HS_REFERENCE_FILES}
        revisions_needed = {_revision_for_year(y) for y in YEARS}

        def is_leaf(rev: str, code: str) -> bool:
            return references[rev].get(code, {}).get("isLeaf") == "1"

        for name, product in PRODUCTS.items():
            codes = set(product["codes"])
            for code in codes:
                in_h5, in_h6 = is_leaf("H5", code), is_leaf("H6", code)

                if in_h5 and in_h6:
                    linked = any(
                        r["hs2022"] == code and r["hs2017"] == code for r in correlation
                    )
                    assert linked, (
                        f"{name}: HS code {code!r} is a valid leaf in both HS2017 "
                        f"and HS2022, but the WCO/UNSD correlation table doesn't "
                        f"link them as the same line item -- the number may have "
                        f"been reassigned to a different product between editions"
                    )
                    continue

                if in_h6 and not in_h5 and "H5" in revisions_needed:
                    predecessors = {r["hs2017"] for r in correlation if r["hs2022"] == code}
                    assert predecessors & codes, (
                        f"{name}: HS code {code!r} (HS2022) didn't exist before "
                        f"2022; its HS2017 predecessor(s) {sorted(predecessors)} "
                        f"must also be in 'codes' to cover years before the "
                        f"HS2022 cutover"
                    )

                if in_h5 and not in_h6 and "H6" in revisions_needed:
                    successors = {r["hs2022"] for r in correlation if r["hs2017"] == code}
                    assert successors & codes, (
                        f"{name}: HS code {code!r} (HS2017) was retired in "
                        f"HS2022; its successor(s) {sorted(successors)} must "
                        f"also be in 'codes' to cover years from 2022 onward"
                    )


class TestGeographyLookups:
    def test_distance_keys_are_numeric_country_codes(self):
        for code, km in DISTANCE_FROM_KABUL_KM.items():
            assert COUNTRY_CODE_PATTERN.match(code), f"invalid distance key {code!r}"
            assert km > 0

    def test_distance_covers_scored_markets(self):
        # DISTANCE_FROM_KABUL_KM is generated from reference/distance_from_kabul_km.csv
        # (CEPII GeoDist) joined through NUMERIC_TO_ISO3 -- every scored market should
        # resolve except this documented gap (see build_distance_reference.py: CEPII's
        # 2011 vintage has no entry for Palestine or Montenegro, nor a usable proxy).
        known_gap = {"275", "499"}  # PSE, MNE
        missing = set(NUMERIC_TO_ISO3) - set(DISTANCE_FROM_KABUL_KM)
        assert missing == known_gap, f"distance coverage gap changed unexpectedly: {missing}"

    def test_distance_values_are_plausible(self):
        # Spot-check real great-circle capital distances (CEPII GeoDist) against
        # known geography, now that these aren't hand-typed round numbers.
        assert DISTANCE_FROM_KABUL_KM["586"] < 500      # Pakistan -- closest neighbour
        assert DISTANCE_FROM_KABUL_KM["842"] > 10_000    # USA -- far side of the globe
        assert DISTANCE_FROM_KABUL_KM["586"] < DISTANCE_FROM_KABUL_KM["842"]

    def test_language_similarity_in_valid_range(self):
        for code, sim in LANGUAGE_SIMILARITY.items():
            assert COUNTRY_CODE_PATTERN.match(code), f"invalid language key {code!r}"
            assert 0.0 <= sim <= 1.0

    def test_language_similarity_covers_scored_markets(self):
        # LANGUAGE_SIMILARITY is generated from reference/language_similarity_afg.csv
        # (DICL) joined through NUMERIC_TO_ISO3 -- DICL has full coverage of the
        # 111 markets the pipeline scores, unlike the CEPII distance data.
        missing = set(NUMERIC_TO_ISO3) - set(LANGUAGE_SIMILARITY)
        assert not missing, f"language coverage gap: {missing}"

    def test_language_similarity_values_are_plausible(self):
        # Spot-check against known linguistics, now that these aren't hand-typed
        # guesses: Dari's closest relatives (Tajik, Farsi) should clearly outrank
        # a distant, unrelated-language market like the USA.
        assert LANGUAGE_SIMILARITY["762"] > 0.3   # Tajikistan -- Tajik ~= Dari
        assert LANGUAGE_SIMILARITY["364"] > 0.3   # Iran -- Farsi ~= Dari
        assert LANGUAGE_SIMILARITY["842"] < LANGUAGE_SIMILARITY["364"]  # USA
