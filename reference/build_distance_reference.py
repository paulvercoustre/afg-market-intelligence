"""
Regenerates reference/distance_from_kabul_km.csv from CEPII's GeoDist dataset.

GeoDist (Mayer & Zignago, 2011) is CEPII's standard gravity-model distance
dataset, published under the Etalab 2.0 open licence:
https://www.cepii.fr/cepii/en/bdd_modele/bdd_modele_item.asp?id=6

This script reads dist_cepii's `distcap` column (great-circle distance in km
between national capitals) for every country paired with Afghanistan, and
writes the whole thing to a checked-in CSV -- so scoring never needs to hit
CEPII at run time, and the numbers are traceable to a citable source instead
of a hand-typed guess.

Usage:
    Download dist_cepii.dta from https://www.cepii.fr/distance/dist_cepii.dta,
    then run:
        python reference/build_distance_reference.py path/to/dist_cepii.dta

Re-run only if CEPII ships a new release of GeoDist; the output CSV is what
config.py actually reads at import time.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

AFGHANISTAN_ISO3 = "AFG"
OUTPUT_PATH = Path(__file__).parent / "distance_from_kabul_km.csv"

# CEPII's 2011 vintage predates a few current ISO-3 codes we need (NUMERIC_TO_ISO3
# in config.py uses current codes, since that's what the World Bank API expects).
# Remap onto the equivalent/successor entity CEPII does have:
#   ROU (Romania) -> CEPII still files it under the pre-2002 code "ROM" -- same
#     country, same capital, so this is an exact match, not an approximation.
#   SRB (Serbia) -> CEPII has no post-2006 breakup entry, only "YUG"
#     (Yugoslavia/Serbia-Montenegro), whose listed capital is Belgrade -- also
#     Serbia's capital today, so distcap carries over unchanged.
# MNE (Montenegro) and PSE (Palestine) have no CEPII entry or usable proxy and
# are left uncovered here; scoring falls back to a neutral default for them,
# same as before this dataset existed.
ISO3_REMAP = {"ROM": "ROU", "YUG": "SRB"}


def main(dta_path: str) -> None:
    df = pd.read_stata(dta_path)
    afg = df[(df["iso_o"] == AFGHANISTAN_ISO3) & (df["iso_d"] != AFGHANISTAN_ISO3)].copy()
    afg = afg.dropna(subset=["distcap"]).sort_values("iso_d")
    afg["iso_d"] = afg["iso_d"].replace(ISO3_REMAP)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["iso3", "distance_km"])
        for _, row in afg.iterrows():
            writer.writerow([row["iso_d"], round(float(row["distcap"]))])

    print(f"Wrote {len(afg)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python reference/build_distance_reference.py path/to/dist_cepii.dta")
        sys.exit(1)
    main(sys.argv[1])
