"""
Regenerates reference/language_similarity_afg.csv from the DICL dataset.

DICL (Domestic and International Common Language Database; Gurevich, Herman,
Toubal & Yotov, 2025, Scientific Data) is a global bilateral dataset of
linguistic connections built from Ethnologue speaker data, published under
CC BY-NC-ND 4.0: https://doi.org/10.7910/DVN/8WGJTL
Source used here: https://catalog.data.gov/dataset/domestic-and-international-common-language-database-dicl

reference/dicl.csv is the raw extract (242 countries x 242 countries, columns
ISO3, ISO3_2, col, cnl, lp, cl). This script pulls just the rows paired with
Afghanistan and the two components the scoring model actually blends:
  - cnl: common native language index (literal shared-native-language overlap)
  - lp:  linguistic proximity (mutual intelligibility across related-but-
         distinct languages, e.g. Dari <-> Farsi <-> Tajik)
It deliberately drops `col` (common official language) and the dataset's own
`cl` composite -- `cl` is (col + cnl + lp) / 3, which lets a binary official-
language flag dominate the score (e.g. it ranks Turkmenistan above Iran and
Tajikistan on the strength of Turkmen's minor constitutional status in
Afghanistan, despite Dari being far closer to Farsi/Tajik in actual mutual
intelligibility). config.py blends cnl and lp itself instead.

Usage:
    python reference/build_language_reference.py
"""

from __future__ import annotations

import csv
from pathlib import Path

AFGHANISTAN_ISO3 = "AFG"
INPUT_PATH = Path(__file__).parent / "dicl.csv"
OUTPUT_PATH = Path(__file__).parent / "language_similarity_afg.csv"


def main() -> None:
    with open(INPUT_PATH, encoding="utf-8", newline="") as f:
        rows = [
            row for row in csv.DictReader(f)
            if row["ISO3"] == AFGHANISTAN_ISO3 and row["ISO3_2"] != AFGHANISTAN_ISO3
        ]
    rows.sort(key=lambda r: r["ISO3_2"])

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["iso3", "cnl", "lp"])
        for row in rows:
            writer.writerow([row["ISO3_2"], row["cnl"], row["lp"]])

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
