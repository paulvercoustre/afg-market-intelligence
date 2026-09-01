"""
Configuration for Afghanistan Trade Intelligence Tool.
This file is the single source of truth for product definitions
and the opportunity scoring model.
"""

AFGHANISTAN_CODE = 'AFG'
AFGHANISTAN_NUMERIC = '4'

YEARS = [2021, 2022, 2023, 2024, 2025]

TOP_N_MARKETS = 10

# Price competitiveness thresholds (% difference vs market average)
PRICE_COMPETITIVENESS = {
    'substantially_below_market': -10,   # more than 10% below market avg
    'below_market': 0,                   # up to 10% below market avg
    'near_market': 10,                   # within 10% above market avg
    # above 10% → 'Above Market'
}

# ── Opportunity score weights (must sum to 1.0) ────────────────────────────────
# Each dimension is normalised to 0–100 before weighting.
OPPORTUNITY_SCORE_WEIGHTS = {
    "market_size": 0.20,         # global import volume for the product
    "market_growth": 0.18,       # CAGR of global imports in this market
    "market_quality": 0.13,      # World Bank governance + LPI composite
    "price_competitiveness": 0.13,  # Afghan price vs market average
    "tariff": 0.12,              # effective import tariff rate from WITS
    "afg_foothold": 0.10,        # existing Afghan export presence
    "distance": 0.10,            # geographic proximity to Kabul
    "language": 0.04,            # language / cultural similarity
}
# fta_status (preferential trade access) is deliberately excluded from the
# composite: WITS's AFG-specific (partner=004) tariff schedule returns
# "NoRecordsFound" for every reporter checked (India, Pakistan, Iran,
# Germany, Turkiye, Bangladesh), so has_fta is False and score_fta is 0 for
# 100% of rows in practice -- a weight that can never move the score. Its
# 0.02 share was folded into "tariff" above, which already prices in the
# actual applied rate WITS does report (AHS or MFN). score_fta/has_fta are
# still computed and stored (etl/transform.py, indicators table) in case
# WITS coverage improves -- just not weighted into opportunity_score.

# Tariff scoring: maps tariff rate % to a 0–100 score.
# 0% → 100, 10% → 70, 20% → 40, 33%+ → 0  (linear: score = max(0, 100 - rate * 3))
TARIFF_SCORE_PER_PCT = 3.0

# Outlier band for cross-supplier unit-price comparison in
# _price_competitiveness() (etl/transform.py): a supplier's implied unit
# price is excluded from market_avg_price_usd if it falls outside
# [median / PRICE_OUTLIER_BAND_MULTIPLIER, median * PRICE_OUTLIER_BAND_MULTIPLIER].
# Same band CEPII uses when cleaning raw Comtrade unit values for the same
# reason (mismatched quantity units across reporters) -- see Berthou &
# Emlinger, "The Trade Unit Values Database", CEPII Working Paper 2011-10,
# §2.3 and Appendix A2. Named here (not inlined) so its sensitivity can be
# tested directly -- see TestPriceOutlierBandRobustness in
# etl/tests/test_transform.py.
PRICE_OUTLIER_BAND_MULTIPLIER = 10.0

# Reported quantity units (etl/fetch.py's Comtrade qtyUnitCode resolution)
# that are a genuinely different, more economically meaningful price basis
# than net_weight_kg -- not just weight at a different scale. Validated
# empirically (2026-08) across all 38 products: within every product, when
# *any* supplier reports a unit at all, every supplier that does agrees on
# the same one -- so per-product consistency doesn't need to be computed at
# query time, just gated on the unit being one of these types. "carat"
# (Lapis Lazuli, worked) was deliberately left out despite being just as
# consistent -- it's still a weight unit, proportional to kg by a fixed
# 5000:1 factor, so using it wouldn't change the price signal, only add a
# second, redundant weight-basis path.
#   m² -- Woven Carpets, Knotted Carpets: carpets are naturally priced by
#         area, not weight.
#   u  -- Cashmere Sweaters: finished garments are naturally priced per
#         piece, not weight.
# _unit_price() and _price_competitiveness() (etl/transform.py) use this
# only when EVERY row on the relevant side (Afghanistan's own flow, or a
# given competitor) reports the exact same one of these units -- otherwise
# they fall back to net_weight_kg exactly as before.
NATIVE_UNIT_PRICE_BASES = {"m²", "u"}

# Distance scoring reference ceiling: the greatest possible great-circle
# distance between two points on Earth (antipodal, ~half the circumference).
# Used to log-normalise score_distance -- gravity-model trade literature
# treats distance's effect on trade as multiplicative (an elasticity on
# ln(distance), not a linear one; see e.g. Disdier & Head 2008's meta-analysis
# of the distance-trade relationship), matching how score_market_size and
# score_afg_foothold already log-scale dollar values for the same reason.
MAX_GREAT_CIRCLE_DISTANCE_KM = 20_015

# ── Comtrade numeric reporter code → ISO-3 alpha code ──────────────────────────
# NB: Comtrade uses non-standard codes for a few countries (India 699, USA 842,
# Switzerland 757, France 251, Norway 579) — these must match the codes that
# actually appear in trade data, not ISO 3166 numeric. Keys must never be
# zero-padded: real Comtrade reporter codes in trade data (and therefore
# indicators.market_code) never carry a leading zero, even for naturally
# short codes like Algeria (12) or Austria (40).
# Verified by name against the live api.worldbank.org/v2/country list — see
# tests/test_etl_fetch.py.
NUMERIC_TO_ISO3: dict[str, str] = {
    "586": "PAK", "699": "IND", "364": "IRN", "860": "UZB", "762": "TJK",
    "795": "TKM", "398": "KAZ", "417": "KGZ", "156": "CHN", "784": "ARE",
    "682": "SAU", "792": "TUR", "634": "QAT", "414": "KWT", "512": "OMN",
    "48": "BHR", "400": "JOR", "368": "IRQ", "818": "EGY", "276": "DEU",
    "826": "GBR", "528": "NLD", "251": "FRA", "380": "ITA", "56": "BEL",
    "724": "ESP", "757": "CHE", "40": "AUT", "616": "POL", "203": "CZE",
    "752": "SWE", "246": "FIN", "579": "NOR", "208": "DNK", "372": "IRL",
    "300": "GRC", "642": "ROU", "100": "BGR", "348": "HUN", "703": "SVK",
    "842": "USA", "124": "CAN", "484": "MEX", "76": "BRA", "32": "ARG",
    "392": "JPN", "410": "KOR", "702": "SGP", "458": "MYS", "360": "IDN",
    "764": "THA", "704": "VNM", "50": "BGD", "144": "LKA", "524": "NPL",
    "104": "MMR", "608": "PHL", "36": "AUS", "554": "NZL", "710": "ZAF",
    "566": "NGA", "12": "DZA", "504": "MAR", "231": "ETH", "643": "RUS",
    "804": "UKR", "112": "BLR", "31": "AZE", "268": "GEO", "51": "ARM",
    "64": "BTN", "462": "MDV",
    "70": "BIH", "96": "BRN", "191": "HRV", "196": "CYP", "233": "EST",
    "266": "GAB", "275": "PSE", "320": "GTM", "344": "HKG", "352": "ISL",
    "376": "ISR", "384": "CIV", "404": "KEN", "418": "LAO", "422": "LBN",
    "428": "LVA", "430": "LBR", "440": "LTU", "442": "LUX", "450": "MDG",
    "470": "MLT", "480": "MUS", "496": "MNG", "498": "MDA", "499": "MNE",
    "508": "MOZ", "604": "PER", "620": "PRT", "646": "RWA", "686": "SEN",
    "688": "SRB", "705": "SVN", "788": "TUN", "800": "UGA", "807": "MKD",
    "834": "TZA", "858": "URY", "887": "YEM", "894": "ZMB",
}

# ── Geographic distance from Kabul, Afghanistan ─────────────────────────────────
# Great-circle capital-to-capital distance (km), from CEPII's GeoDist dataset
# (Mayer & Zignago, 2011): https://www.cepii.fr/cepii/en/bdd_modele/bdd_modele_item.asp?id=6
# reference/distance_from_kabul_km.csv is the checked-in extract (keyed by
# ISO-3); reference/build_distance_reference.py regenerates it from CEPII's
# raw dist_cepii.dta. Joined here through NUMERIC_TO_ISO3 to key by the same
# Comtrade reporter codes the rest of the scoring model uses.
def _load_distance_from_kabul_km() -> dict[str, int]:
    import csv
    from pathlib import Path

    csv_path = Path(__file__).parent / "reference" / "distance_from_kabul_km.csv"
    with open(csv_path, encoding="utf-8", newline="") as f:
        iso3_to_km = {row["iso3"]: round(float(row["distance_km"])) for row in csv.DictReader(f)}

    return {
        code: iso3_to_km[iso3]
        for code, iso3 in NUMERIC_TO_ISO3.items()
        if iso3 in iso3_to_km
    }


DISTANCE_FROM_KABUL_KM: dict[str, int] = _load_distance_from_kabul_km()

# ── Language similarity to Dari-Pashto (0.0 → 1.0) ──────────────────────────────
# Blend of two DICL indices (Gurevich, Herman, Toubal & Yotov, 2025 --
# https://doi.org/10.7910/DVN/8WGJTL): `lp` (linguistic proximity -- mutual
# intelligibility across related-but-distinct languages, e.g. Dari<->Farsi<->
# Tajik) at the dominant weight, plus `cnl` (common native language -- literal
# shared-native-language population overlap) at a lower weight so two
# countries that speak the exact same named language outrank two that merely
# speak close relatives. reference/language_similarity_afg.csv is the
# checked-in extract (keyed by ISO-3); reference/build_language_reference.py
# regenerates it from reference/dicl.csv. Deliberately excludes DICL's `col`
# (common official language) -- blending that in (as DICL's own `cl` composite
# does) lets a binary official-language flag dominate: it ranks Turkmenistan
# above Iran/Tajikistan on the strength of Turkmen's minor constitutional
# status in Afghanistan, despite Dari being far closer to Farsi/Tajik in
# actual mutual intelligibility.
LANGUAGE_SIMILARITY_LP_WEIGHT = 0.8  # remainder (0.2) goes to cnl


def _load_language_similarity() -> dict[str, float]:
    import csv
    from pathlib import Path

    csv_path = Path(__file__).parent / "reference" / "language_similarity_afg.csv"
    with open(csv_path, encoding="utf-8", newline="") as f:
        iso3_to_score = {
            row["iso3"]: (
                LANGUAGE_SIMILARITY_LP_WEIGHT * float(row["lp"])
                + (1 - LANGUAGE_SIMILARITY_LP_WEIGHT) * float(row["cnl"])
            )
            for row in csv.DictReader(f)
        }

    return {
        code: round(iso3_to_score[iso3], 4)
        for code, iso3 in NUMERIC_TO_ISO3.items()
        if iso3 in iso3_to_score
    }


LANGUAGE_SIMILARITY: dict[str, float] = _load_language_similarity()
# Default language similarity for markets with no DICL match
LANGUAGE_SIMILARITY_DEFAULT = 0.05

# NB: preferential/FTA trade access is no longer a static lookup here -- it's
# derived live in etl/transform.py from WITS's own AHS/MFN partner-segment
# indicator (indicators.tariff_indicator == 'AHS'), which is already fetched
# for the tariff dimension. See enrich_indicators_with_scores().

# Products keyed by primary HS code (6-digit, no dots).
# 'codes' lists all HS codes that roll up into one product entry.
PRODUCTS = {
    # ── Tree nuts ──────────────────────────────────────────────────────────
    'Almonds In-Shell': {
        'codes': ['080211'],
        'category': 'Tree Nuts',
        'description': 'Almonds, in-shell (fresh or dried)',
    },
    'Almonds Shelled': {
        'codes': ['080212'],
        'category': 'Tree Nuts',
        'description': 'Almonds, shelled (fresh or dried)',
    },
    'Walnuts In-Shell': {
        'codes': ['080231'],
        'category': 'Tree Nuts',
        'description': 'Walnuts, in-shell',
    },
    'Walnuts Shelled': {
        'codes': ['080232'],
        'category': 'Tree Nuts',
        'description': 'Walnuts, shelled',
    },
    'Pistachios In-Shell': {
        'codes': ['080251'],
        'category': 'Tree Nuts',
        'description': 'Pistachios, in-shell',
    },
    'Pistachios Shelled': {
        'codes': ['080252'],
        'category': 'Tree Nuts',
        'description': 'Pistachios, shelled',
    },
    'Pine Nuts': {
        # NB: HS2022 (effective 2022-01-01) split pine nuts out of the old
        # "other nuts n.e.c." bucket into dedicated in-shell/shelled codes.
        # 080290 is only valid for 2021 (HS2017); 080291/080292 only from
        # 2022 onward (HS2022). All three are needed to cover the full
        # YEARS window -- see reference/hs_h5.json and reference/hs_h6.json.
        'codes': ['080290', '080291', '080292'],
        'category': 'Tree Nuts',
        'description': 'Pine nuts, fresh or dried, in-shell or shelled',
    },

    # ── Spices & herbs ─────────────────────────────────────────────────────
    'Saffron': {
        'codes': ['091020'],
        'category': 'Spices & Herbs',
        'description': 'Saffron (stigmas, crushed or ground)',
    },
    'Cumin Seeds': {
        'codes': ['090931'],
        'category': 'Spices & Herbs',
        'description': 'Cumin seeds',
    },
    'Fenugreek': {
        # NB: HS2022 split African cherry bark (Prunus africana) out of this
        # n.e.c. bucket into its own code (121160) -- unrelated to fenugreek,
        # so 121190 keeps the same scope for our purposes across revisions.
        # See reference/hs2017_hs2022_correlation.csv.
        'codes': ['121190'],
        'category': 'Spices & Herbs',
        'description': 'Fenugreek and other plants used in pharmacy/perfumery',
    },
    'Asafoetida': {
        'codes': ['130190'],
        'category': 'Spices & Herbs',
        'description': 'Other vegetable saps and extracts (incl. asafoetida/hing)',
    },
    'Liquorice Root': {
        # NB: the dedicated liquorice-root code (121110) is valid but almost
        # never used by reporters (2 global records across 2021-2024).
        # Real root trade is reported under this broader "other plants n.e.c."
        # catch-all instead, alongside unrelated goods (ginseng, coca leaf,
        # poppy straw, ephedra). See README for details.
        'codes': ['121190'],
        'category': 'Spices & Herbs',
        'description': 'Liquorice roots',
    },
    'Liquorice Extract': {
        'codes': ['130212'],
        'category': 'Spices & Herbs',
        'description': 'Liquorice extract',
    },

    # ── Dried fruits ───────────────────────────────────────────────────────
    'Dried Grapes (Raisins)': {
        'codes': ['080620'],
        'category': 'Dried Fruits',
        'description': 'Dried grapes, including raisins and sultanas',
    },
    'Dried Apricots': {
        'codes': ['081310'],
        'category': 'Dried Fruits',
        'description': 'Dried apricots',
    },
    'Dried Figs': {
        'codes': ['080420'],
        'category': 'Dried Fruits',
        'description': 'Dried figs',
    },
    'Dried Pomegranate': {
        'codes': ['081340'],
        'category': 'Dried Fruits',
        # NB: pomegranate has no dedicated HS6 code -- this is the catch-all
        # "other dried fruit, n.e.c." bucket, so figures include unrelated
        # minor dried fruits alongside pomegranate. See README for details.
        'description': 'Other dried fruits (incl. dried pomegranate)',
    },
    # NB: no dedicated "dried mulberries" code exists anywhere in the HS
    # classification -- mulberries only appear combined with raspberries/
    # blackberries/loganberries under fresh (081020) or cooked/frozen (081120)
    # headings, never in the dried-fruit chapter. Tracked as two separate
    # products below rather than one "Dried Mulberries" entry. See README.
    'Mulberries (Fresh)': {
        'codes': ['081020'],
        'category': 'Fresh Fruits',
        'description': 'Raspberries, blackberries, mulberries and loganberries, fresh',
    },
    'Mulberries (Prepared/Frozen)': {
        'codes': ['081120'],
        'category': 'Fresh Fruits',
        'description': 'Raspberries, blackberries, mulberries etc., uncooked or cooked, frozen',
    },

    # ── Fresh fruits ───────────────────────────────────────────────────────
    'Fresh Grapes': {
        'codes': ['080610'],
        'category': 'Fresh Fruits',
        'description': 'Fresh grapes',
    },
    'Fresh Pomegranate': {
        'codes': ['081090'],
        'category': 'Fresh Fruits',
        # NB: pomegranate has no dedicated HS6 code -- this is the catch-all
        # "other fresh fruit, n.e.c." bucket, so figures include unrelated
        # minor fresh fruits alongside pomegranate. See README for details.
        'description': 'Other fresh fruit (incl. pomegranate)',
    },
    'Watermelons': {
        'codes': ['080711'],
        'category': 'Fresh Fruits',
        'description': 'Watermelons (fresh)',
    },
    'Melons': {
        'codes': ['080719'],
        'category': 'Fresh Fruits',
        'description': 'Melons, other than watermelons (fresh)',
    },
    'Apricots': {
        'codes': ['080910'],
        'category': 'Fresh Fruits',
        'description': 'Fresh apricots',
    },

    # ── Carpets & textiles ─────────────────────────────────────────────────
    'Knotted Carpets': {
        'codes': ['570110'],
        'category': 'Carpets & Textiles',
        'description': 'Knotted carpets of wool or fine animal hair (hand-made)',
    },
    # NB: kilims have no dedicated HS6 code of their own -- Comtrade's 570210
    # ("woven, not tufted or flocked" carpets) explicitly names kelim/kilim
    # rugs as part of this same category, so they're not tracked as a
    # separate product. See README.
    'Woven Carpets': {
        'codes': ['570210'],
        'category': 'Carpets & Textiles',
        'description': 'Woven carpets of wool or fine animal hair (hand-made), incl. kelim/kilim rugs',
    },

    # ── Luxury fibres ──────────────────────────────────────────────────────
    'Raw Cashmere': {
        'codes': ['510211'],
        'category': 'Luxury Fibres',
        'description': 'Cashmere (Kashmir goat hair), not carded or combed',
    },
    'Processed Cashmere': {
        'codes': ['510531'],
        'category': 'Luxury Fibres',
        'description': 'Wool and fine or coarse animal hair, carded or combed (including combed wool in fragments, Kashmir goat hair)',
    },
    'Cashmere Sweaters': {
        'codes': ['611012'],
        'category': 'Luxury Fibres',
        'description': 'Sweaters/pullovers of cashmere (fine animal hair)',
    },
    'Karakul Sheepskin': {
        'codes': ['410510'],
        'category': 'Luxury Fibres',
        'description': 'Tanned or dressed sheepskin leather',
    },

    # ── Minerals & stones ──────────────────────────────────────────────────
    # Lapis lazuli has no HS6 code of its own -- it falls under these three
    # broader precious/semi-precious stone categories depending on processing
    # stage. Tracked as three separate products. See README.
    'Lapis Lazuli (Unworked)': {
        'codes': ['710310'],
        'category': 'Minerals & Stones',
        'description': 'Precious/semi-precious stones (incl. lapis lazuli), unworked or simply sawn/roughly shaped',
    },
    'Lapis Lazuli (Worked)': {
        'codes': ['710399'],
        'category': 'Minerals & Stones',
        'description': 'Precious/semi-precious stones (incl. lapis lazuli), worked, not strung/mounted/set',
    },
    'Lapis Lazuli (Articles)': {
        'codes': ['711620'],
        'category': 'Minerals & Stones',
        'description': 'Articles of precious/semi-precious stones (incl. lapis lazuli)',
    },
    'Marble & Travertine (Crude)': {
        'codes': ['251511'],
        'category': 'Minerals & Stones',
        'description': 'Marble and travertine, crude or roughly trimmed',
    },
    'Marble & Travertine (Cut)': {
        'codes': ['251512'],
        'category': 'Minerals & Stones',
        'description': 'Marble and travertine, merely cut into blocks or slabs',
    },
    'Talc': {
        'codes': ['252620'],
        'category': 'Minerals & Stones',
        'description': 'Talc, crushed or powdered',
    },

    # ── Oilseeds ───────────────────────────────────────────────────────────
    'Sesame Seeds': {
        'codes': ['120740'],
        'category': 'Oilseeds',
        'description': 'Sesame seeds',
    },
    'Flaxseed / Linseed': {
        'codes': ['120400'],
        'category': 'Oilseeds',
        'description': 'Linseed (flaxseed), whether or not broken',
    },
}
