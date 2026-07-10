"""
Configuration for Afghanistan Trade Intelligence Tool.
This file is the single source of truth for product definitions
and the opportunity scoring model.
"""

AFGHANISTAN_CODE = 'AFG'
AFGHANISTAN_NUMERIC = '4'

YEARS = [2021, 2022, 2023, 2024]

TOP_N_MARKETS = 10

# Price competitiveness thresholds (% difference vs market average)
PRICE_COMPETITIVENESS = {
    'highly_competitive': -10,   # more than 10% below market avg
    'competitive': 0,            # up to 10% below market avg
    'average': 10,               # within 10% above market avg
    # above 10% → 'Above Market'
}

# ── Opportunity score weights (must sum to 1.0) ────────────────────────────────
# Each dimension is normalised to 0–100 before weighting.
OPPORTUNITY_SCORE_WEIGHTS = {
    "market_size": 0.20,         # global import volume for the product
    "market_growth": 0.18,       # CAGR of global imports in this market
    "market_quality": 0.13,      # World Bank governance + LPI composite
    "price_competitiveness": 0.13,  # Afghan price vs market average
    "tariff": 0.10,              # effective import tariff rate from WITS
    "afg_foothold": 0.10,        # existing Afghan export presence
    "distance": 0.10,            # geographic proximity to Kabul
    "language": 0.04,            # language / cultural similarity
    "fta_status": 0.02,          # preferential trade access (small bonus — mostly captured in tariff)
}

# Tariff scoring: maps tariff rate % to a 0–100 score.
# 0% → 100, 10% → 70, 20% → 40, 33%+ → 0  (linear: score = max(0, 100 - rate * 3))
TARIFF_SCORE_PER_PCT = 3.0

# ── Geographic distance from Kabul, Afghanistan (approximate km) ───────────────
# Keyed by Comtrade reporter numeric string (same codes used in trade data).
# NB: Comtrade uses non-standard numeric codes for some countries — India 699,
# USA 842, Switzerland 757, France 251, Norway 579 — not the ISO 3166 numeric.
# Values are straight-line distances; rough approximations sufficient for scoring.
DISTANCE_FROM_KABUL_KM: dict[str, int] = {
    "586": 450,    # Pakistan
    "699": 1000,   # India
    "364": 600,    # Iran
    "860": 600,    # Uzbekistan
    "762": 400,    # Tajikistan
    "795": 800,    # Turkmenistan
    "398": 1500,   # Kazakhstan
    "417": 900,    # Kyrgyzstan
    "156": 3000,   # China
    "784": 2000,   # UAE
    "682": 2500,   # Saudi Arabia
    "792": 3000,   # Turkey
    "634": 2200,   # Qatar
    "414": 2200,   # Kuwait
    "512": 2300,   # Oman
    "048": 2100,   # Bahrain
    "400": 2500,   # Jordan
    "368": 1500,   # Iraq
    "818": 3500,   # Egypt
    "276": 5500,   # Germany
    "826": 6000,   # United Kingdom
    "528": 6000,   # Netherlands
    "251": 6000,   # France
    "380": 5500,   # Italy
    "56": 6000,    # Belgium
    "724": 6500,   # Spain
    "757": 5500,   # Switzerland
    "040": 5000,   # Austria
    "616": 5500,   # Poland
    "203": 5500,   # Czech Republic
    "752": 5500,   # Sweden
    "246": 5500,   # Finland
    "579": 5500,   # Norway
    "208": 6000,   # Denmark
    "372": 6000,   # Ireland
    "300": 4500,   # Greece
    "642": 4500,   # Romania
    "100": 4500,   # Bulgaria
    "348": 5000,   # Hungary
    "703": 5000,   # Slovakia
    "842": 12000,  # United States
    "124": 11000,  # Canada
    "484": 13000,  # Mexico
    "076": 13000,  # Brazil
    "032": 14000,  # Argentina
    "392": 6500,   # Japan
    "410": 6000,   # South Korea
    "702": 5000,   # Singapore
    "458": 5000,   # Malaysia
    "360": 5500,   # Indonesia
    "764": 4500,   # Thailand
    "704": 5000,   # Vietnam
    "050": 2000,   # Bangladesh
    "144": 3000,   # Sri Lanka
    "524": 1500,   # Nepal
    "104": 3500,   # Myanmar
    "608": 5500,   # Philippines
    "036": 9000,   # Australia
    "554": 12000,  # New Zealand
    "710": 8000,   # South Africa
    "566": 7000,   # Nigeria
    "012": 7000,   # Algeria
    "504": 7000,   # Morocco
    "231": 4000,   # Ethiopia
    "643": 3500,   # Russia
    "804": 4000,   # Ukraine
    "112": 5000,   # Belarus
    "031": 2000,   # Azerbaijan
    "268": 2500,   # Georgia
    "051": 2200,   # Armenia
}

# ── Language / cultural similarity to Dari-Pashto (0.0 → 1.0) ────────────────
# Based on mutual intelligibility and trade-communication practicality.
LANGUAGE_SIMILARITY: dict[str, float] = {
    "364": 1.0,    # Iran — Farsi ≈ Dari
    "762": 0.9,    # Tajikistan — Tajik ≈ Dari
    "586": 0.5,    # Pakistan — Urdu/Pashto overlap
    "860": 0.3,    # Uzbekistan — historical Persian lingua franca
    "795": 0.3,    # Turkmenistan
    "398": 0.25,   # Kazakhstan
    "417": 0.25,   # Kyrgyzstan
    "699": 0.2,    # India — Hindi/Urdu shares Persian loanwords
    "050": 0.2,    # Bangladesh
    "144": 0.15,   # Sri Lanka
    "524": 0.15,   # Nepal
    "792": 0.2,    # Turkey — Ottoman Persian heritage
    "031": 0.2,    # Azerbaijan
    "268": 0.15,   # Georgia
    "682": 0.3,    # Saudi Arabia — Arabic loanwords in Dari
    "784": 0.3,    # UAE
    "368": 0.3,    # Iraq
    "400": 0.3,    # Jordan
    "634": 0.3,    # Qatar
    "818": 0.3,    # Egypt
    "842": 0.1,    # USA
    "826": 0.1,    # UK
    "124": 0.1,    # Canada
    "036": 0.1,    # Australia
}
# Default language similarity for unlisted countries
LANGUAGE_SIMILARITY_DEFAULT = 0.05

# ── Free Trade Agreement / preferential trade access ──────────────────────────
# Afghanistan FTA memberships: SAARC/SAPTA, ECO, GSP in EU/UK/others.
# Values: 'full', 'partial', or None.
FTA_STATUS: dict[str, str] = {
    # SAARC Preferential Trading Arrangement (SAPTA)
    "699": "partial",   # India
    "586": "partial",   # Pakistan
    "050": "partial",   # Bangladesh
    "144": "partial",   # Sri Lanka
    "524": "partial",   # Nepal
    "064": "partial",   # Bhutan
    "462": "partial",   # Maldives
    # ECO Trade Agreement
    "364": "partial",   # Iran
    "792": "partial",   # Turkey
    "398": "partial",   # Kazakhstan
    "417": "partial",   # Kyrgyzstan
    "762": "partial",   # Tajikistan
    "795": "partial",   # Turkmenistan
    "860": "partial",   # Uzbekistan
    "031": "partial",   # Azerbaijan
    # EU GSP+ (significant tariff reduction)
    "276": "partial",   # Germany
    "528": "partial",   # Netherlands
    "251": "partial",   # France
    "380": "partial",   # Italy
    "56": "partial",    # Belgium
    "724": "partial",   # Spain
    "757": "partial",   # Switzerland (GSP)
    "040": "partial",   # Austria
    "616": "partial",   # Poland
    "203": "partial",   # Czech Republic
    "752": "partial",   # Sweden
    "246": "partial",   # Finland
    "579": "partial",   # Norway (GSP)
    "208": "partial",   # Denmark
    "372": "partial",   # Ireland
    "300": "partial",   # Greece
    "642": "partial",   # Romania
    "100": "partial",   # Bulgaria
    "348": "partial",   # Hungary
    "826": "partial",   # UK (post-Brexit GSP)
}

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
        'codes': ['080253'],
        'category': 'Tree Nuts',
        'description': 'Pistachios, in-shell',
    },
    'Pistachios Shelled': {
        'codes': ['080254'],
        'category': 'Tree Nuts',
        'description': 'Pistachios, shelled',
    },
    'Pine Nuts': {
        'codes': ['080290'],
        'category': 'Tree Nuts',
        'description': 'Other nuts, fresh or dried (incl. pine nuts)',
    },

    # ── Spices & herbs ─────────────────────────────────────────────────────
    'Saffron': {
        'codes': ['091020'],
        'category': 'Spices & Herbs',
        'description': 'Saffron (stigmas, crushed or ground)',
    },
    'Cumin Seeds': {
        'codes': ['090920'],
        'category': 'Spices & Herbs',
        'description': 'Cumin seeds',
    },
    'Fenugreek': {
        'codes': ['121190'],
        'category': 'Spices & Herbs',
        'description': 'Fenugreek and other plants used in pharmacy/perfumery',
    },
    'Asafoetida': {
        'codes': ['130219'],
        'category': 'Spices & Herbs',
        'description': 'Other vegetable saps and extracts (incl. asafoetida/hing)',
    },
    'Liquorice Root': {
        'codes': ['121110'],
        'category': 'Spices & Herbs',
        'description': 'Liquorice roots',
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
        'codes': ['081390'],
        'category': 'Dried Fruits',
        'description': 'Other dried fruits (incl. dried pomegranate)',
    },
    'Dried Mulberries': {
        'codes': ['081320'],
        'category': 'Dried Fruits',
        'description': 'Dried prunes and mulberries',
    },

    # ── Fresh fruits ───────────────────────────────────────────────────────
    'Fresh Grapes': {
        'codes': ['080610'],
        'category': 'Fresh Fruits',
        'description': 'Fresh grapes',
    },
    'Fresh Pomegranate': {
        'codes': ['081080'],
        'category': 'Fresh Fruits',
        'description': 'Other fresh fruit (incl. pomegranate)',
    },
    'Melons': {
        'codes': ['080790'],
        'category': 'Fresh Fruits',
        'description': 'Other melons (fresh)',
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
    'Woven Carpets': {
        'codes': ['570210'],
        'category': 'Carpets & Textiles',
        'description': 'Woven carpets of wool or fine animal hair (hand-made)',
    },
    'Kilims': {
        'codes': ['570391'],
        'category': 'Carpets & Textiles',
        'description': 'Kelim, sumak, karamanie and similar flat-woven rugs',
    },

    # ── Luxury fibres ──────────────────────────────────────────────────────
    'Raw Cashmere': {
        'codes': ['510211'],
        'category': 'Luxury Fibres',
        'description': 'Cashmere (Kashmir goat hair), not carded or combed',
    },
    'Processed Cashmere': {
        'codes': ['510212'],
        'category': 'Luxury Fibres',
        'description': 'Cashmere (Kashmir goat hair), carded or combed',
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
    'Lapis Lazuli': {
        'codes': ['711299'],
        'category': 'Minerals & Stones',
        'description': 'Precious/semi-precious stones (incl. lapis lazuli), unworked',
    },
    'Marble & Travertine': {
        'codes': ['251621'],
        'category': 'Minerals & Stones',
        'description': 'Marble and travertine, crude or rough',
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
