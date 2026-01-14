"""
Indicator calculation functions for trade analysis.
Calculates market size, growth rates, market shares, and price competitiveness.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any
from config import AFGHANISTAN_CODE

# Set up logging
logger = logging.getLogger(__name__)


def identify_top_global_import_markets(hs_code: str, years: List[int], top_n: int = 5, unified_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Identify top global import markets for a product by total import value.

    This finds the countries that import the most of a given HS code globally,
    providing strategic market opportunities rather than just Afghanistan's current markets.

    Parameters:
    -----------
    hs_code : str
        HS product code (6-digit)
    years : List[int]
        List of years to analyze
    top_n : int
        Number of top markets to return
    unified_data : pd.DataFrame, optional
        Pre-fetched unified global data. If provided, skips API call.

    Returns:
    --------
    pd.DataFrame
        DataFrame with top import markets ranked by total import value
        Columns: partner, trade_value, rank
    """
    from comtrade_client import fetch_global_imports

    # Use pre-fetched unified data if available
    global_imports = fetch_global_imports(hs_code, years, unified_data=unified_data)

    if global_imports.empty:
        logger.warning(f"No global import data found for HS {hs_code}")
        return pd.DataFrame(columns=['partner', 'trade_value', 'rank'])

    # Use most recent year for ranking
    latest_year = global_imports['year'].max()
    df = global_imports[global_imports['year'] == latest_year].copy()

    if df.empty:
        return pd.DataFrame(columns=['partner', 'trade_value', 'rank'])

    # Aggregate by importer (partner column contains importer codes)
    market_totals = df.groupby('partner')['trade_value'].sum().reset_index()

    # Sort by import value descending
    market_totals = market_totals.sort_values('trade_value', ascending=False)

    # Add rank and filter to top N
    market_totals['rank'] = range(1, len(market_totals) + 1)

    return market_totals.head(top_n)


def identify_top_markets(df_exports: pd.DataFrame, top_n: int = 10,
                        year: Optional[int] = None) -> pd.DataFrame:
    """
    Identify top N markets by export value.
    
    Parameters:
    -----------
    df_exports : pd.DataFrame
        DataFrame with columns: year, partner, trade_value
    top_n : int
        Number of top markets to return (default: 10)
    year : int, optional
        Specific year to analyze. If None, uses most recent year.
    
    Returns:
    --------
    pd.DataFrame
        DataFrame with top markets ranked by export value
    """
    if df_exports.empty:
        logger.warning("Empty export data provided to identify_top_markets")
        return pd.DataFrame(columns=['partner', 'trade_value', 'rank'])
    
    # Filter by year if specified, otherwise use most recent
    if year is not None:
        df = df_exports[df_exports['year'] == year].copy()
    else:
        latest_year = df_exports['year'].max()
        df = df_exports[df_exports['year'] == latest_year].copy()
    
    if df.empty:
        return pd.DataFrame(columns=['partner', 'trade_value', 'rank'])
    
    # Aggregate by partner (sum across all products if multiple)
    market_totals = df.groupby('partner')['trade_value'].sum().reset_index()
    
    # Sort by value descending
    market_totals = market_totals.sort_values('trade_value', ascending=False)
    
    # Add rank
    market_totals['rank'] = range(1, len(market_totals) + 1)
    
    # Return top N
    return market_totals.head(top_n)


def calculate_growth_rate(df_exports: pd.DataFrame, market_code: str,
                          years: List[int]) -> Dict[str, float]:
    """
    Calculate growth rate for a specific market over the past 5 years.
    
    Parameters:
    -----------
    df_exports : pd.DataFrame
        DataFrame with columns: year, partner, trade_value
    market_code : str
        Partner country code (e.g., 'IND' for India)
    years : List[int]
        List of years (should be sorted, e.g., [2019, 2020, 2021, 2022, 2023])
    
    Returns:
    --------
    dict
        Dictionary with:
        - 'yoy_growth': Year-over-year growth rate (most recent year)
        - 'cagr': Compound Annual Growth Rate over the period
        - 'absolute_growth': Absolute change in value
        - 'growth_percentage': Percentage change over the period
    """
    # Filter for this market
    market_data = df_exports[df_exports['partner'] == market_code].copy()
    
    if market_data.empty:
        logger.warning(f"No export data found for market {market_code}")
        return {
            'yoy_growth': None,
            'cagr': None,
            'absolute_growth': None,
            'growth_percentage': None
        }
    
    # Aggregate by year (sum if multiple records per year)
    yearly_totals = market_data.groupby('year')['trade_value'].sum().reset_index()
    yearly_totals = yearly_totals.sort_values('year')
    
    if len(yearly_totals) < 2:
        return {
            'yoy_growth': None,
            'cagr': None,
            'absolute_growth': None,
            'growth_percentage': None
        }
    
    # Get first and last year values
    first_year = yearly_totals['year'].min()
    last_year = yearly_totals['year'].max()
    
    first_value = yearly_totals[yearly_totals['year'] == first_year]['trade_value'].values[0]
    last_value = yearly_totals[yearly_totals['year'] == last_year]['trade_value'].values[0]
    
    # Calculate year-over-year growth (most recent)
    if len(yearly_totals) >= 2:
        prev_year = yearly_totals.iloc[-2]['year']
        prev_value = yearly_totals.iloc[-2]['trade_value']
        if prev_value > 0:
            yoy_growth = ((last_value - prev_value) / prev_value) * 100
        else:
            yoy_growth = None
    else:
        yoy_growth = None
    
    # Calculate CAGR
    n_years = last_year - first_year
    if n_years > 0 and first_value > 0:
        cagr = (((last_value / first_value) ** (1 / n_years)) - 1) * 100
    else:
        cagr = None
    
    # Absolute and percentage growth
    absolute_growth = last_value - first_value
    if first_value > 0:
        growth_percentage = ((last_value - first_value) / first_value) * 100
    else:
        growth_percentage = None
    
    return {
        'yoy_growth': yoy_growth,
        'cagr': cagr,
        'absolute_growth': absolute_growth,
        'growth_percentage': growth_percentage,
        'first_year': int(first_year),
        'last_year': int(last_year),
        'first_value': float(first_value),
        'last_value': float(last_value)
    }


def calculate_market_share(afg_exports: pd.DataFrame, total_imports: pd.DataFrame,
                          market_code: str, year: Optional[int] = None) -> float:
    """
    Calculate Afghanistan's market share in a specific market.
    
    Parameters:
    -----------
    afg_exports : pd.DataFrame
        Afghanistan's exports to this market (columns: year, partner, trade_value)
    total_imports : pd.DataFrame
        Total imports for this market (columns: year, partner_code, total_import_value)
    market_code : str
        Partner country code
    year : int, optional
        Specific year. If None, uses most recent year.
    
    Returns:
    --------
    float
        Market share as percentage (0-100)
    """
    # Filter Afghanistan exports to this market
    afg_to_market = afg_exports[afg_exports['partner'] == market_code].copy()
    
    if afg_to_market.empty:
        logger.warning(f"No Afghanistan export data found for market {market_code}")
        return 0.0
    
    # Filter total imports for this market
    market_imports = total_imports[total_imports['partner_code'] == market_code].copy()
    
    if market_imports.empty:
        logger.warning(f"No import data found for market {market_code}")
        return 0.0
    
    # Use specific year or most recent
    if year is not None:
        afg_value = afg_to_market[afg_to_market['year'] == year]['trade_value'].sum()
        total_value = market_imports[market_imports['year'] == year]['total_import_value'].sum()
    else:
        latest_year = min(afg_to_market['year'].max(), market_imports['year'].max())
        afg_value = afg_to_market[afg_to_market['year'] == latest_year]['trade_value'].sum()
        total_value = market_imports[market_imports['year'] == latest_year]['total_import_value'].sum()
    
    if total_value > 0:
        return (afg_value / total_value) * 100
    else:
        return 0.0


def get_market_rank(afg_exports: pd.DataFrame, all_suppliers: pd.DataFrame,
                   market_code: str, year: Optional[int] = None) -> int:
    """
    Get Afghanistan's rank among all suppliers to a market.
    
    Parameters:
    -----------
    afg_exports : pd.DataFrame
        Afghanistan's exports (columns: year, partner, trade_value)
    all_suppliers : pd.DataFrame
        All suppliers' exports to this market (columns: year, supplier, import_value)
    market_code : str
        Partner country code
    year : int, optional
        Specific year. If None, uses most recent year.
    
    Returns:
    --------
    int
        Rank (1 = highest, None if not found)
    """
    # Filter for this market
    market_suppliers = all_suppliers[all_suppliers.get('supplier', pd.Series()).notna()].copy()
    
    # If supplier column doesn't exist, try to find it
    if 'supplier' not in market_suppliers.columns:
        # Check if partner column exists (might be named differently)
        if 'partner' in market_suppliers.columns:
            market_suppliers = market_suppliers.rename(columns={'partner': 'supplier'})
        else:
            return None
    
    # Filter for this market - need to check how market_code is represented
    # This depends on the structure of all_suppliers DataFrame
    # Assuming it's filtered by market already or has a market column
    
    # Use specific year or most recent
    if year is not None:
        market_suppliers = market_suppliers[market_suppliers['year'] == year]
    else:
        latest_year = market_suppliers['year'].max()
        market_suppliers = market_suppliers[market_suppliers['year'] == latest_year]
    
    if market_suppliers.empty:
        return None
    
    # Get Afghanistan's export value to this market
    afg_to_market = afg_exports[afg_exports['partner'] == market_code].copy()
    if year is not None:
        afg_value = afg_to_market[afg_to_market['year'] == year]['trade_value'].sum()
    else:
        latest_year = afg_to_market['year'].max()
        afg_value = afg_to_market[afg_to_market['year'] == latest_year]['trade_value'].sum()
    
    # Rank all suppliers by import_value
    market_suppliers = market_suppliers.sort_values('import_value', ascending=False)
    market_suppliers['rank'] = range(1, len(market_suppliers) + 1)
    
    # Find Afghanistan's rank
    # Note: We need to compare afg_value with supplier values
    # Find where afg_value would rank
    afg_rank = None
    for idx, row in market_suppliers.iterrows():
        if row['import_value'] <= afg_value:
            afg_rank = row['rank']
            break
    
    # If Afghanistan's value is higher than all, it's rank 1
    if afg_rank is None and afg_value > 0:
        # Check if Afghanistan is in the supplier list
        afg_in_list = market_suppliers[market_suppliers['supplier'] == AFGHANISTAN_CODE]
        if not afg_in_list.empty:
            afg_rank = int(afg_in_list.iloc[0]['rank'])
        else:
            # Afghanistan not in list, need to insert
            # Count how many have higher value
            higher_count = (market_suppliers['import_value'] > afg_value).sum()
            afg_rank = higher_count + 1
    
    return afg_rank


def get_competitor_shares(all_suppliers: pd.DataFrame, market_code: str,
                         top_n: int = 5, year: Optional[int] = None) -> pd.DataFrame:
    """
    Get top competitors' market shares in a specific market.

    Parameters:
    -----------
    all_suppliers : pd.DataFrame
        All suppliers' exports to this market (columns: year, supplier, trade_value)
    market_code : str
        Partner country code
    top_n : int
        Number of top competitors to return (default: 5)
    year : int, optional
        Specific year. If None, uses most recent year.

    Returns:
    --------
    pd.DataFrame
        DataFrame with top competitors and their market shares
    """
    # Filter for this market and year
    market_data = all_suppliers.copy()
    
    if 'supplier' not in market_data.columns and 'partner' in market_data.columns:
        market_data = market_data.rename(columns={'partner': 'supplier'})
    
    if year is not None:
        market_data = market_data[market_data['year'] == year]
    else:
        latest_year = market_data['year'].max()
        market_data = market_data[market_data['year'] == latest_year]
    
    if market_data.empty:
        return pd.DataFrame(columns=['supplier', 'trade_value', 'market_share', 'rank'])

    # Calculate total market size
    total_imports = market_data['trade_value'].sum()

    # Calculate market share for each supplier
    market_data = market_data.copy()
    if total_imports > 0:
        market_data['market_share'] = (market_data['trade_value'] / total_imports) * 100
    else:
        market_data['market_share'] = 0.0

    # Sort by trade value
    market_data = market_data.sort_values('trade_value', ascending=False)
    market_data['rank'] = range(1, len(market_data) + 1)
    
    # Return top N
    return market_data.head(top_n)[['supplier', 'trade_value', 'market_share', 'rank']]


def calculate_unit_price(df_exports: pd.DataFrame, 
                        partner: Optional[str] = None,
                        year: Optional[int] = None) -> float:
    """
    Calculate unit price (FOB value / volume) for exports.
    
    Parameters:
    -----------
    df_exports : pd.DataFrame
        DataFrame with columns: year, partner, trade_value, trade_quantity
    partner : str, optional
        Specific partner. If None, aggregates all partners.
    year : int, optional
        Specific year. If None, uses most recent year.
    
    Returns:
    --------
    float
        Unit price (value per unit of quantity), or None if quantity is missing/zero
    """
    df = df_exports.copy()
    
    # Filter by partner if specified
    if partner is not None:
        df = df[df['partner'] == partner]
    
    # Filter by year if specified
    if year is not None:
        df = df[df['year'] == year]
    else:
        latest_year = df['year'].max()
        df = df[df['year'] == latest_year]
    
    if df.empty:
        logger.debug(f"No data found for unit price calculation (partner={partner}, year={year})")
        return None
    
    # Check if quantity column exists
    if 'trade_quantity' not in df.columns:
        logger.warning("Quantity data not available for unit price calculation")
        return None
    
    # Aggregate totals
    total_value = df['trade_value'].sum()
    total_quantity = df['trade_quantity'].sum()
    
    if total_quantity > 0:
        unit_price = total_value / total_quantity
        logger.debug(f"Calculated unit price: {unit_price:.2f} (value={total_value:.2f}, qty={total_quantity:.2f})")
        return unit_price
    else:
        logger.warning("Total quantity is zero or missing, cannot calculate unit price")
        return None


def compare_to_global_average(afg_unit_price: float, global_prices: pd.DataFrame,
                              year: Optional[int] = None) -> Dict[str, float]:
    """
    Compare Afghanistan's unit price to global average.
    
    Parameters:
    -----------
    afg_unit_price : float
        Afghanistan's unit price
    global_prices : pd.DataFrame
        Global price data (columns: year, trade_value, trade_quantity)
    year : int, optional
        Specific year. If None, uses most recent year.
    
    Returns:
    --------
    dict
        Dictionary with:
        - 'global_avg_price': Global average unit price
        - 'price_difference': Absolute difference (AFG - Global)
        - 'price_difference_pct': Percentage difference
        - 'competitiveness': 'Above', 'Below', or 'Equal' to global average
    """
    if afg_unit_price is None:
        return {
            'global_avg_price': None,
            'price_difference': None,
            'price_difference_pct': None,
            'competitiveness': None
        }
    
    # Filter by year if specified
    if year is not None:
        global_data = global_prices[global_prices['year'] == year]
    else:
        latest_year = global_prices['year'].max()
        global_data = global_prices[global_prices['year'] == latest_year]
    
    if global_data.empty:
        return {
            'global_avg_price': None,
            'price_difference': None,
            'price_difference_pct': None,
            'competitiveness': None
        }
    
    # Calculate global average unit price
    total_value = global_data['trade_value'].sum()
    total_quantity = global_data['trade_quantity'].sum()
    
    if total_quantity > 0:
        global_avg_price = total_value / total_quantity
    else:
        return {
            'global_avg_price': None,
            'price_difference': None,
            'price_difference_pct': None,
            'competitiveness': None
        }
    
    # Calculate differences
    price_difference = afg_unit_price - global_avg_price
    if global_avg_price > 0:
        price_difference_pct = (price_difference / global_avg_price) * 100
    else:
        price_difference_pct = None
    
    # Determine competitiveness
    if abs(price_difference) < 0.01:  # Essentially equal
        competitiveness = 'Equal'
    elif price_difference > 0:
        competitiveness = 'Above'
    else:
        competitiveness = 'Below'
    
    return {
        'global_avg_price': float(global_avg_price),
        'price_difference': float(price_difference),
        'price_difference_pct': float(price_difference_pct) if price_difference_pct is not None else None,
        'competitiveness': competitiveness
    }


def compare_to_competitors_in_market(afg_unit_price: float, competitor_data: pd.DataFrame,
                                    market_code: str) -> Dict[str, Any]:
    """
    Compare Afghanistan's unit price to competitors in a specific target market.

    This is more relevant than global comparisons since it shows pricing within
    the actual market where Afghanistan is competing.

    Parameters:
    -----------
    afg_unit_price : float
        Afghanistan's unit price
    competitor_data : pd.DataFrame
        Competitor import data for the target market
    market_code : str
        The target market code

    Returns:
    --------
    dict
        Dictionary with market-specific price comparison
    """
    if afg_unit_price is None or competitor_data.empty:
        return {
            'market_avg_price': None,
            'afg_vs_market_pct': None,
            'competitiveness': None
        }

    # Calculate unit prices for all suppliers in this market
    competitor_data = competitor_data.copy()

    # Calculate unit prices where quantity > 0
    competitor_data['unit_price'] = competitor_data.apply(
        lambda row: row['trade_value'] / row['trade_quantity']
        if pd.notna(row['trade_quantity']) and row['trade_quantity'] > 0 else None,
        axis=1
    )

    # Get valid price data
    valid_prices = competitor_data['unit_price'].dropna()

    if valid_prices.empty:
        return {
            'market_avg_price': None,
            'afg_vs_market_pct': None,
            'competitiveness': None
        }

    # Calculate market average price (excluding Afghanistan)
    market_avg_price = valid_prices.mean()

    # Calculate Afghanistan's position vs market
    if market_avg_price > 0:
        price_diff_pct = ((afg_unit_price - market_avg_price) / market_avg_price) * 100

        if price_diff_pct < -10:
            competitiveness = 'Highly Competitive'
        elif price_diff_pct < 0:
            competitiveness = 'Competitive'
        elif price_diff_pct < 10:
            competitiveness = 'Average'
        else:
            competitiveness = 'Above Market'
    else:
        price_diff_pct = None
        competitiveness = None

    return {
        'market_avg_price': float(market_avg_price),
        'afg_vs_market_pct': float(price_diff_pct) if price_diff_pct is not None else None,
        'competitiveness': competitiveness
    }


def compare_to_competitors(afg_unit_price: float, competitor_prices: pd.DataFrame,
                          top_n: int = 5, year: Optional[int] = None) -> Dict:
    """
    Compare Afghanistan's unit price to top competitors in a market.
    
    Parameters:
    -----------
    afg_unit_price : float
        Afghanistan's unit price
    competitor_prices : pd.DataFrame
        Competitor price data (columns: year, supplier, import_value, import_quantity)
    top_n : int
        Number of top competitors to compare (default: 5)
    year : int, optional
        Specific year. If None, uses most recent year.
    
    Returns:
    --------
    dict
        Dictionary with competitor comparisons
    """
    if afg_unit_price is None:
        return {
            'competitor_prices': [],
            'afg_rank': None,
            'avg_competitor_price': None
        }
    
    # Filter by year if specified
    if year is not None:
        comp_data = competitor_prices[competitor_prices['year'] == year].copy()
    else:
        latest_year = competitor_prices['year'].max()
        comp_data = competitor_prices[competitor_prices['year'] == latest_year].copy()
    
    if comp_data.empty:
        return {
            'competitor_prices': [],
            'afg_rank': None,
            'avg_competitor_price': None
        }
    
    # Calculate unit prices for competitors
    # Need import_value and import_quantity columns
    if 'import_quantity' not in comp_data.columns:
        # Try to calculate from available data or return empty
        return {
            'competitor_prices': [],
            'afg_rank': None,
            'avg_competitor_price': None
        }
    
    comp_data = comp_data.copy()
    comp_data['unit_price'] = comp_data['import_value'] / comp_data['import_quantity'].replace(0, np.nan)
    
    # Sort by import value and get top N
    comp_data = comp_data.sort_values('import_value', ascending=False)
    top_competitors = comp_data.head(top_n).copy()
    
    # Calculate average competitor price
    valid_prices = top_competitors['unit_price'].dropna()
    if len(valid_prices) > 0:
        avg_competitor_price = valid_prices.mean()
    else:
        avg_competitor_price = None
    
    # Find Afghanistan's rank
    all_prices = comp_data['unit_price'].dropna().sort_values(ascending=False)
    afg_rank = None
    if len(all_prices) > 0:
        # Count how many have lower prices (more competitive)
        lower_prices = (all_prices < afg_unit_price).sum()
        afg_rank = lower_prices + 1
    
    # Prepare competitor list
    competitor_list = []
    for idx, row in top_competitors.iterrows():
        if pd.notna(row['unit_price']):
            competitor_list.append({
                'supplier': row.get('supplier', 'Unknown'),
                'unit_price': float(row['unit_price']),
                'import_value': float(row['import_value'])
            })
    
    return {
        'competitor_prices': competitor_list,
        'afg_rank': afg_rank,
        'avg_competitor_price': float(avg_competitor_price) if avg_competitor_price is not None else None
    }
