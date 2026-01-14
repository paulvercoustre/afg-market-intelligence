"""
Configuration file for Afghanistan Trade Intelligence Tool
"""

# Afghanistan country code
AFGHANISTAN_CODE = 'AFG'

# Year range for analysis (past 4 years for more data)
YEARS = [2021, 2022, 2023, 2024]

# Number of top markets to analyze (expanded for comprehensive analysis)
TOP_N_MARKETS = 10

# UN Comtrade API configuration
# Note: UN Comtrade uses HS codes (Harmonized System)
# HS codes can be specified with or without dots (e.g., 080211 or 0802.11)
# Comtrade typically uses 6-digit HS codes

# Product definitions with individual HS codes
# Note: UN Comtrade accepts HS codes in various formats
# Each HS code is now analyzed separately for more precise insights
PRODUCTS = {
    'Almonds In-Shell': {
        'codes': ['080211'],
        'description': 'Almonds, in-shell (fresh or dried)',
        'hs_codes_with_dots': ['0802.11']
    },
    'Almonds Shelled': {
        'codes': ['080212'],
        'description': 'Almonds, shelled (fresh or dried)',
        'hs_codes_with_dots': ['0802.12']
    },
    'Saffron': {
        'codes': ['091020'],
        'description': 'Saffron (stigmas, crushed or ground)',
        'hs_codes_with_dots': ['0910.20']
    },
    'Fresh Grapes': {
        'codes': ['080610'],
        'description': 'Fresh Grapes',
        'hs_codes_with_dots': ['0806.10']
    },
    'Dried Grapes': {
        'codes': ['080620'],
        'description': 'Dried Grapes (including Raisins/Sultanas)',
        'hs_codes_with_dots': ['0806.20']
    },
    'Knotted Carpets': {
        'codes': ['570110'],
        'description': 'Knotted Carpets (wool/fine animal hair, hand-woven)',
        'hs_codes_with_dots': ['5701.10']
    },
    'Woven Carpets': {
        'codes': ['570210'],
        'description': 'Woven Carpets (wool/fine animal hair, hand-woven)',
        'hs_codes_with_dots': ['5702.10']
    },
    'Raw Cashmere': {
        'codes': ['510211'],
        'description': 'Cashmere hair of Kashmir goats, raw',
        'hs_codes_with_dots': ['5102.11']
    },
    'Cashmere Sweaters': {
        'codes': ['611012'],
        'description': 'Cashmere sweaters, pullovers, cardigans (wool/fine animal hair)',
        'hs_codes_with_dots': ['6110.12']
    }
}
