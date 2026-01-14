"""
UN Comtrade API client for fetching granular trade data.
Handles data retrieval from UN Comtrade API for specific HS codes.
"""

import comtradeapicall
import pandas as pd
import time
import logging
import requests
from typing import List, Optional, Dict
from config import AFGHANISTAN_CODE

# Disable SSL verification for development (workaround for certificate issues)
# TODO: Remove this in production and ensure proper certificate validation
import ssl
import urllib3

# Create unverified SSL context
ssl._create_default_https_context = ssl._create_unverified_context

# Disable urllib3 warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Monkey patch urllib3 to use unverified context
original_poolmanager_init = urllib3.PoolManager.__init__

def patched_poolmanager_init(self, *args, **kwargs):
    kwargs['cert_reqs'] = 'CERT_NONE'
    kwargs['assert_hostname'] = False
    return original_poolmanager_init(self, *args, **kwargs)

urllib3.PoolManager.__init__ = patched_poolmanager_init

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rate limiting: delay between API calls (seconds)
API_DELAY = 1.0

# SSL verification (set to False for development if certificate issues occur)
SSL_VERIFY = True  # Set to False to disable SSL certificate verification

# UN Comtrade API subscription key (set via environment variable or config)
# Get your key from: https://unstats.un.org/wiki/display/comtrade/UN+Comtrade+API
COMTRADE_API_KEY = None  # Will be set from environment or config

# Common country code to name mapping (UN Comtrade numeric codes)
COUNTRY_CODES = {
    '4': 'Afghanistan', '36': 'Australia', '40': 'Austria', '56': 'Belgium',
    '100': 'Bulgaria', '124': 'Canada', '156': 'China', '203': 'Czechia',
    '208': 'Denmark', '233': 'Estonia', '246': 'Finland', '251': 'France',
    '276': 'Germany', '300': 'Greece', '348': 'Hungary', '356': 'India',
    '360': 'Indonesia', '364': 'Iran', '372': 'Ireland', '376': 'Israel',
    '380': 'Italy', '392': 'Japan', '398': 'Kazakhstan', '410': 'South Korea',
    '428': 'Latvia', '440': 'Lithuania', '458': 'Malaysia', '484': 'Mexico',
    '528': 'Netherlands', '554': 'New Zealand', '578': 'Norway', '586': 'Pakistan',
    '616': 'Poland', '620': 'Portugal', '642': 'Romania', '643': 'Russia',
    '682': 'Saudi Arabia', '699': 'India', '702': 'Singapore', '703': 'Slovakia',
    '705': 'Slovenia', '710': 'South Africa', '724': 'Spain', '752': 'Sweden',
    '756': 'Switzerland', '764': 'Thailand', '792': 'Turkey', '784': 'UAE',
    '804': 'Ukraine', '826': 'United Kingdom', '840': 'USA', '842': 'USA',
    '860': 'Uzbekistan', '704': 'Vietnam', '0': 'World', '000': 'World'
}






def set_api_key(api_key: str):
    """Set the UN Comtrade API subscription key."""
    global COMTRADE_API_KEY
    COMTRADE_API_KEY = api_key
    logger.info("UN Comtrade API key set")


def get_country_name(code: str) -> str:
    """Convert country code to country name for display."""
    code_str = str(code).split('.')[0]  # Handle float codes like '842.0'
    return COUNTRY_CODES.get(code_str, code_str)


def fetch_afghanistan_exports_batch(hs_codes: List[str], years: List[int],
                                   partner: Optional[str] = None) -> pd.DataFrame:
    """
    Fetch Afghanistan export data for multiple HS codes in batch.
    
    Since Afghanistan doesn't report to UN Comtrade, we use mirror data:
    Query all countries' IMPORTS from Afghanistan (partnerCode=4).
    This effectively gives us Afghanistan's exports.

    Parameters:
    -----------
    hs_codes : List[str]
        List of HS product codes
    years : List[int]
        List of years to fetch data for
    partner : str, optional
        Specific partner country code. If None, fetches all partners.

    Returns:
    --------
    pd.DataFrame
        DataFrame with columns: year, partner, trade_value, trade_quantity, netweight
    """
    if COMTRADE_API_KEY is None:
        logger.warning("UN Comtrade API key not set. Set it using set_api_key() or environment variable COMTRADE_API_KEY")

    # Convert years list to comma-separated string for batch API call
    years_str = ','.join(str(year) for year in years)
    logger.info(f"Fetching Afghanistan exports (via mirror data) for HS codes {hs_codes} for years: {years_str}")

    # Convert HS codes to comma-separated string
    hs_codes_str = ','.join(hs_codes)
    logger.info(f"Batch fetching for HS codes: {hs_codes_str}")

    # Afghanistan numeric code
    afghanistan_code = '4'

    # Convert partner/reporter code if provided (for filtering to specific importer)
    reporter_code = None
    if partner:
        try:
            reporter_code = comtradeapicall.convertCountryIso3ToCode(partner)
        except:
            reporter_code = partner

    # MIRROR DATA APPROACH:
    # Query: All countries (reporters) importing FROM Afghanistan (partner)
    # This gives us Afghanistan's exports as reported by importing countries
    logger.info(f"  Using mirror data: querying world imports from Afghanistan")
    response = comtradeapicall.getFinalData(
            subscription_key=COMTRADE_API_KEY,
            typeCode='C',
            freqCode='A',
            clCode='HS',
            period=years_str,
            reporterCode=reporter_code,  # None = all reporters (all importing countries)
            cmdCode=hs_codes_str,
            flowCode='M',  # Import (other countries importing FROM Afghanistan)
            partnerCode=afghanistan_code,  # Afghanistan as the partner/exporter
            partner2Code=None,
            customsCode=None,
            motCode=None
        )
    time.sleep(API_DELAY)  # Rate limiting

    # Initialize df before processing
    df = None
    
    # Process response
    if response is not None:
        if isinstance(response, pd.DataFrame) and not response.empty:
            df = response
            logger.info(f"  ✓ Retrieved mirror data: {len(df)} records")
        elif isinstance(response, list) and len(response) > 0:
            df = pd.DataFrame(response)
            logger.info(f"  ✓ Retrieved mirror data: {len(df)} records")

    # Check if we have data
    if df is None or (hasattr(df, 'empty') and df.empty):
        logger.warning("No mirror data retrieved from API")
        return pd.DataFrame()

    if df is not None and not df.empty and isinstance(df, pd.DataFrame):
        logger.info(f"✅ Processing {len(df)} rows of mirror data")
        try:
            # For MIRROR DATA: reporter = importing country (our "partner")
            # Create standardized columns explicitly to avoid duplicates
            
            # Year column (check sources in order of preference)
            if 'refYear' in df.columns:
                df['year'] = pd.to_numeric(df['refYear'], errors='coerce').astype('Int64')
            elif 'period' in df.columns:
                df['year'] = pd.to_numeric(df['period'], errors='coerce').astype('Int64')
            
            # Trade value
            if 'primaryValue' in df.columns:
                df['trade_value'] = pd.to_numeric(df['primaryValue'], errors='coerce')
            elif 'cifvalue' in df.columns:
                df['trade_value'] = pd.to_numeric(df['cifvalue'], errors='coerce')
            
            # Trade quantity
            if 'qty' in df.columns:
                df['trade_quantity'] = pd.to_numeric(df['qty'], errors='coerce')
            
            # Net weight
            if 'netWgt' in df.columns:
                df['netweight'] = pd.to_numeric(df['netWgt'], errors='coerce')
            
            # HS code
            if 'cmdCode' in df.columns:
                df['hs_code'] = df['cmdCode']
            
            # Partner (importing country = reporter in mirror data)
            # Use reporterCode (numeric) for consistent matching with global imports data
            if 'reporterCode' in df.columns and df['reporterCode'].notna().any():
                df['partner'] = df['reporterCode'].astype(str)
                logger.info(f"  Partner set from 'reporterCode': {df['partner'].iloc[0] if len(df) > 0 else 'empty'}")
            elif 'reporterISO' in df.columns and df['reporterISO'].notna().any():
                df['partner'] = df['reporterISO']
                logger.info(f"  Partner set from 'reporterISO': {df['partner'].iloc[0] if len(df) > 0 else 'empty'}")
            else:
                logger.warning(f"  Could not set partner - available reporter columns: {[c for c in df.columns if 'reporter' in c.lower()]}")
            
            # Select only the columns we need
            output_cols = ['year', 'partner', 'trade_value', 'trade_quantity', 'netweight', 'hs_code']
            available_cols = [c for c in output_cols if c in df.columns]
            df = df[available_cols].copy()
            
            logger.info(f"Successfully processed {len(df)} mirror data rows")
            logger.info(f"Output columns: {list(df.columns)}")

        except Exception as e:
            logger.error(f"Error processing API response: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return pd.DataFrame()
    else:
        logger.warning(f"API returned invalid or empty response")
        return pd.DataFrame()

    # For batch processing, return the processed DataFrame directly
    logger.info(f"Returning processed DataFrame with shape: {df.shape if hasattr(df, 'shape') else 'no shape'}")
    logger.info(f"Final return - df is None: {df is None}, df empty: {df.empty if hasattr(df, 'empty') else 'no empty attr'}")
    if hasattr(df, 'shape') and df.shape[0] > 0:
        logger.info(f"Sample of returned data: {df.iloc[0].to_dict() if len(df) > 0 else 'empty'}")
    return df


def fetch_afghanistan_exports(hs_code: str, years: List[int],
                              partner: Optional[str] = None) -> pd.DataFrame:
    """
    Fetch Afghanistan export data for a specific product and years.
    
    Since Afghanistan doesn't report to UN Comtrade, we use mirror data:
    Query countries' IMPORTS from Afghanistan (partnerCode=4).
    
    Parameters:
    -----------
    hs_code : str
        HS product code (6-digit, e.g., '080211' or '0802.11')
    years : List[int]
        List of years to fetch data for
    partner : str, optional
        Specific importing country code. If None, fetches all importers.
    
    Returns:
    --------
    pd.DataFrame
        DataFrame with columns: year, partner, trade_value, trade_quantity, netweight
    """
    if COMTRADE_API_KEY is None:
        logger.warning("UN Comtrade API key not set. Set it using set_api_key() or environment variable COMTRADE_API_KEY")
    
    all_data = []

    # Convert HS code to format without dots if needed
    hs_code_clean = hs_code.replace('.', '')

    # Afghanistan numeric code
    afghanistan_code = '4'

    # Convert partner/reporter code if provided
    reporter_code = None
    if partner:
        try:
            reporter_code = comtradeapicall.convertCountryIso3ToCode(partner)
        except:
            reporter_code = partner

    # Batch years in single API call when no specific partner is requested
    if reporter_code is None:
        # Batch multiple years in one call for efficiency
        years_str = ','.join(str(year) for year in years)
        logger.info(f"Fetching Afghanistan exports (via mirror) for HS {hs_code_clean} for years: {years_str}")

        try:
            # MIRROR DATA: Query imports FROM Afghanistan - ALL YEARS IN ONE CALL
            response = comtradeapicall.getFinalData(
                subscription_key=COMTRADE_API_KEY,
                typeCode='C',
                freqCode='A',
                clCode='HS',
                period=years_str,  # Multiple years in one call
                reporterCode=reporter_code,  # None = all importing countries
                cmdCode=hs_code_clean,
                flowCode='M',  # Import (from Afghanistan)
                partnerCode=afghanistan_code,  # Afghanistan as exporter
                partner2Code=None,
                customsCode=None,
                motCode=None
            )

            time.sleep(API_DELAY)  # Rate limiting

            # Process response
            if response is not None:
                if isinstance(response, pd.DataFrame) and not response.empty:
                    df = response
                    logger.info(f"  ✓ Retrieved mirror data: {len(df)} records")
                elif isinstance(response, list) and len(response) > 0:
                    df = pd.DataFrame(response)
                    logger.info(f"  ✓ Retrieved mirror data: {len(df)} records")
                else:
                    df = None

            if df is not None and not df.empty:
                # Extract year from refYear or period for batched data
                if 'refYear' in df.columns:
                    df['year'] = pd.to_numeric(df['refYear'], errors='coerce').astype('Int64')
                elif 'period' in df.columns:
                    df['year'] = pd.to_numeric(df['period'], errors='coerce').astype('Int64')

                # Process the DataFrame (mirror data)
                if df is not None and not df.empty and isinstance(df, pd.DataFrame):
                    try:
                        # For MIRROR DATA: reporter = importing country (our "partner")
                        # Create standardized columns explicitly to avoid duplicates

                        # Year column (already extracted above)

                        # Trade value
                        if 'primaryValue' in df.columns:
                            df['trade_value'] = pd.to_numeric(df['primaryValue'], errors='coerce')
                        elif 'cifvalue' in df.columns:
                            df['trade_value'] = pd.to_numeric(df['cifvalue'], errors='coerce')

                        # Trade quantity
                        if 'qty' in df.columns:
                            df['trade_quantity'] = pd.to_numeric(df['qty'], errors='coerce')

                        # Net weight
                        if 'netWgt' in df.columns:
                            df['netweight'] = pd.to_numeric(df['netWgt'], errors='coerce')

                        # HS code
                        if 'cmdCode' in df.columns:
                            df['hs_code'] = df['cmdCode']

                        # Partner (importing country = reporter in mirror data)
                        # Use reporterCode (numeric) for consistent matching with global imports data
                        if 'reporterCode' in df.columns:
                            df['partner'] = df['reporterCode'].astype(str)
                        elif 'reporterISO' in df.columns:
                            df['partner'] = df['reporterISO']

                        # Select only the columns we need
                        output_cols = ['year', 'partner', 'trade_value', 'trade_quantity', 'netweight', 'hs_code']
                        available_cols = [c for c in output_cols if c in df.columns]
                        df = df[available_cols].copy()

                        all_data.append(df)
                        logger.info(f"  ✓ Processed {len(df)} records for batched years")

                    except Exception as e:
                        logger.warning(f"Error processing DataFrame for batched years: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
        except Exception as e:
            logger.error(f"Error fetching batched export data for {hs_code_clean}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
    else:
        # For specific partner queries, still loop through years individually
        for year in years:
            df = None  # Initialize df for this year
            try:
                logger.info(f"Fetching Afghanistan exports (via mirror) for HS {hs_code_clean} in {year}")

                # MIRROR DATA: Query imports FROM Afghanistan
                response = comtradeapicall.getFinalData(
                    subscription_key=COMTRADE_API_KEY,
                    typeCode='C',
                    freqCode='A',
                    clCode='HS',
                    period=str(year),
                    reporterCode=reporter_code,  # Specific importing country
                    cmdCode=hs_code_clean,
                    flowCode='M',  # Import (from Afghanistan)
                    partnerCode=afghanistan_code,  # Afghanistan as exporter
                    partner2Code=None,
                    customsCode=None,
                    motCode=None
                )

                time.sleep(API_DELAY)  # Rate limiting
            
                # Process response
                if response is not None:
                    if isinstance(response, pd.DataFrame) and not response.empty:
                        df = response
                        logger.info(f"  ✓ Retrieved mirror data: {len(df)} records")
                    elif isinstance(response, list) and len(response) > 0:
                        df = pd.DataFrame(response)
                        logger.info(f"  ✓ Retrieved mirror data: {len(df)} records")

                # If no data available, skip this year
                if df is None or (hasattr(df, 'empty') and df.empty):
                    logger.warning(f"  ⚠ No data available for {year}")
                    continue
            
                # Process the DataFrame (mirror data)
                # Process the DataFrame (mirror data)
                if df is not None and not df.empty and isinstance(df, pd.DataFrame):
                    try:
                        # For MIRROR DATA: reporter = importing country (our "partner")
                        # Create standardized columns explicitly to avoid duplicates

                        # Year column
                        if 'refYear' in df.columns:
                            df['year'] = pd.to_numeric(df['refYear'], errors='coerce').astype('Int64')
                        elif 'period' in df.columns:
                            df['year'] = pd.to_numeric(df['period'], errors='coerce').astype('Int64')
                        else:
                            df['year'] = year

                        # Trade value
                        if 'primaryValue' in df.columns:
                            df['trade_value'] = pd.to_numeric(df['primaryValue'], errors='coerce')
                        elif 'cifvalue' in df.columns:
                            df['trade_value'] = pd.to_numeric(df['cifvalue'], errors='coerce')

                        # Trade quantity
                        if 'qty' in df.columns:
                            df['trade_quantity'] = pd.to_numeric(df['qty'], errors='coerce')

                        # Net weight
                        if 'netWgt' in df.columns:
                            df['netweight'] = pd.to_numeric(df['netWgt'], errors='coerce')

                        # HS code
                        if 'cmdCode' in df.columns:
                            df['hs_code'] = df['cmdCode']

                        # Partner (importing country = reporter in mirror data)
                        # Use reporterCode (numeric) for consistent matching with global imports data
                        if 'reporterCode' in df.columns:
                            df['partner'] = df['reporterCode'].astype(str)
                        elif 'reporterISO' in df.columns:
                            df['partner'] = df['reporterISO']

                        # Select only the columns we need
                        output_cols = ['year', 'partner', 'trade_value', 'trade_quantity', 'netweight', 'hs_code']
                        available_cols = [c for c in output_cols if c in df.columns]
                        df = df[available_cols].copy()

                        all_data.append(df)
                        logger.info(f"  ✓ Processed {len(df)} records for {year}")
                    except Exception as e:
                        logger.warning(f"Error processing DataFrame for {year}: {e}")
                        import traceback
                        logger.warning(traceback.format_exc())
                        continue
                else:
                    logger.warning(f"  ⚠ No data returned for {year}")

            except Exception as e:
                import traceback
                logger.error(f"Error fetching export data for {hs_code_clean} in {year}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                continue
    
    if not all_data:
        return pd.DataFrame(columns=['year', 'partner', 'trade_value', 'trade_quantity'])
    
    # Combine all years
    result = pd.concat(all_data, ignore_index=True)
    
    # Select and standardize columns
    columns = ['year', 'partner', 'trade_value']
    if 'trade_quantity' in result.columns:
        columns.append('trade_quantity')
    if 'netweight' in result.columns:
        columns.append('netweight')
    
    result = result[[c for c in columns if c in result.columns]]
    
    return result


def fetch_unified_global_imports(hs_code: str, years: List[int]) -> pd.DataFrame:
    """
    UNIFIED API CALL: Get ALL global import data in one massive query.

    This revolutionary function makes ONE API call to get:
    - Global import rankings (world totals)
    - Market sizes for any country
    - Competitor data for any market
    - All supplier relationships worldwide

    Parameters:
    -----------
    hs_code : str
        HS product code (6-digit)
    years : List[int]
        List of years to fetch data for

    Returns:
    --------
    pd.DataFrame
        Complete global import dataset with all relationships
        Columns: reporterCode, partnerCode, primaryValue, year, etc.
    """
    if COMTRADE_API_KEY is None:
        logger.warning("UN Comtrade API key not set")
        return pd.DataFrame()

    hs_code_clean = hs_code.replace('.', '')
    years_str = ','.join(str(year) for year in years)

    logger.info(f"🚀 UNIFIED GLOBAL IMPORT QUERY: HS {hs_code_clean} for years {years_str}")

    try:
        # THE UNIFIED API CALL - Get EVERYTHING in one call!
        response = comtradeapicall.getFinalData(
            subscription_key=COMTRADE_API_KEY,
            typeCode='C',
            freqCode='A',
            clCode='HS',
            period=years_str,
            reporterCode=None,      # ALL importing countries
            cmdCode=hs_code_clean,
            flowCode='M',           # Import flow
            partnerCode=None,       # ALL suppliers (including World '0')
            partner2Code=None,
            customsCode=None,
            motCode=None
        )

        if response is None or (isinstance(response, pd.DataFrame) and response.empty):
            logger.warning("❌ Unified query returned no data")
            return pd.DataFrame()

        df = response if isinstance(response, pd.DataFrame) else pd.DataFrame(response)

        # Extract year from refYear or period
        if 'refYear' in df.columns:
            df['year'] = pd.to_numeric(df['refYear'], errors='coerce')
        elif 'period' in df.columns:
            df['year'] = pd.to_numeric(df['period'], errors='coerce')

        # Convert codes to strings for consistency
        df['reporterCode'] = df['reporterCode'].astype(str)
        df['partnerCode'] = df['partnerCode'].astype(str)

        # Filter to requested years only
        df = df[df['year'].isin(years)]

        logger.info(f"✅ Unified query successful: {len(df)} records, {df['reporterCode'].nunique()} importers, {df['partnerCode'].nunique()} suppliers")

        return df

    except Exception as e:
        logger.error(f"Unified global import query failed: {e}")
        return pd.DataFrame()


def fetch_market_imports_batch(partner_codes: List[str], hs_code: str,
                              years: List[int], unified_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Fetch total import data for multiple partner markets using unified API call.

    This function extracts market sizes from the unified dataset.
    Uses partnerCode='0' (World aggregate) to get total imports per market.

    Parameters:
    -----------
    partner_codes : List[str]
        List of country codes for importing markets
    hs_code : str
        HS product code (6-digit)
    years : List[int]
        List of years to fetch data for
    unified_data : pd.DataFrame, optional
        Pre-fetched unified global data. If provided, skips API call.

    Returns:
    --------
    pd.DataFrame
        DataFrame with columns: year, partner_code, total_import_value, total_import_quantity
    """
    if not partner_codes:
        return pd.DataFrame(columns=['year', 'partner_code', 'total_import_value', 'total_import_quantity'])

    # Use provided unified data or fetch it
    if unified_data is not None:
        unified_data = unified_data.copy()
    else:
        unified_data = fetch_unified_global_imports(hs_code, years)

    if unified_data.empty:
        return pd.DataFrame(columns=['year', 'partner_code', 'total_import_value', 'total_import_quantity'])

    # Extract world totals for the requested markets
    world_totals = unified_data[
        (unified_data['partnerCode'] == '0') &
        (unified_data['reporterCode'].isin(partner_codes))
    ].copy()

    if world_totals.empty:
        logger.warning(f"No world totals found for markets {partner_codes}")
        return pd.DataFrame(columns=['year', 'partner_code', 'total_import_value', 'total_import_quantity'])

    # Group by reporter (market) and year, sum all imports
    all_data = []
    for partner_code in partner_codes:
        for year in years:
            mask = (world_totals['reporterCode'] == partner_code) & (world_totals['year'] == year)
            year_data = world_totals[mask]

            if not year_data.empty:
                total_value = pd.to_numeric(year_data['primaryValue'], errors='coerce').sum()

                # Note: Quantity data may not be available in world totals
                # We could look at supplier breakdowns, but that would be more complex
                total_quantity = None

                all_data.append({
                    'year': year,
                    'partner_code': partner_code,
                    'total_import_value': total_value,
                    'total_import_quantity': total_quantity
                })

    result = pd.DataFrame(all_data)
    logger.info(f"✅ Extracted market sizes for {len(partner_codes)} markets from unified data")

    return result


def fetch_market_imports(partner_code: str, hs_code: str,
                        years: List[int]) -> pd.DataFrame:
    """
    Fetch total import data for a partner market (for market share calculations).

    This is a convenience function that calls fetch_market_imports_batch for a single market.
    """
    result = fetch_market_imports_batch([partner_code], hs_code, years)
    return result.drop(columns=['partner_code']) if not result.empty else pd.DataFrame(columns=['year', 'total_import_value', 'total_import_quantity'])
    
    if not all_data:
        return pd.DataFrame(columns=['year', 'partner_code', 'total_import_value'])
    
    return pd.DataFrame(all_data)


def fetch_market_imports_by_partner_batch(partner_codes: List[str], hs_code: str,
                                        years: List[int], unified_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Fetch import data for multiple markets broken down by supplier country using unified API call.

    This function extracts supplier breakdowns from the unified dataset.
    Excludes partnerCode='0' (World aggregate) to get actual supplier relationships.

    Parameters:
    -----------
    partner_codes : List[str]
        List of country codes for importing markets
    hs_code : str
        HS product code (6-digit)
    years : List[int]
        List of years to fetch data for
    unified_data : pd.DataFrame, optional
        Pre-fetched unified global data. If provided, skips API call.

    Returns:
    --------
    pd.DataFrame
        DataFrame with columns: year, partner_code, supplier, trade_value, trade_quantity
    """
    if not partner_codes:
        return pd.DataFrame(columns=['year', 'partner_code', 'supplier', 'trade_value'])

    # Use provided unified data or fetch it
    if unified_data is not None:
        unified_data = unified_data.copy()
    else:
        unified_data = fetch_unified_global_imports(hs_code, years)

    if unified_data.empty:
        return pd.DataFrame(columns=['year', 'partner_code', 'supplier', 'trade_value'])

    # Extract supplier relationships (exclude World totals with partnerCode='0')
    supplier_data = unified_data[
        (unified_data['partnerCode'] != '0') &
        (unified_data['reporterCode'].isin(partner_codes))
    ].copy()

    if supplier_data.empty:
        logger.warning(f"No supplier data found for markets {partner_codes}")
        return pd.DataFrame(columns=['year', 'partner_code', 'supplier', 'trade_value'])

    # Create standardized columns
    if 'partnerDesc' in supplier_data.columns:
        supplier_data['supplier'] = supplier_data['partnerDesc']
    else:
        supplier_data['supplier'] = supplier_data['partnerCode']

    supplier_data['trade_value'] = pd.to_numeric(supplier_data['primaryValue'], errors='coerce')

    if 'qty' in supplier_data.columns:
        supplier_data['trade_quantity'] = pd.to_numeric(supplier_data['qty'], errors='coerce')
    elif 'netWgt' in supplier_data.columns:
        supplier_data['trade_quantity'] = pd.to_numeric(supplier_data['netWgt'], errors='coerce')
    else:
        supplier_data['trade_quantity'] = None

    # Add partner_code column for each market
    supplier_data['partner_code'] = supplier_data['reporterCode']

    # Select relevant columns
    columns = ['year', 'partner_code', 'supplier', 'trade_value']
    if 'trade_quantity' in supplier_data.columns:
        columns.append('trade_quantity')

    result = supplier_data[[c for c in columns if c in supplier_data.columns]].copy()

    # Filter to only requested markets and years
    result = result[result['partner_code'].isin(partner_codes) & result['year'].isin(years)]

    logger.info(f"✅ Extracted supplier data for {len(partner_codes)} markets from unified data: {len(result)} records")

    return result


def fetch_market_imports_by_partner(partner_code: str, hs_code: str,
                                   years: List[int]) -> pd.DataFrame:
    """
    Fetch import data for a market broken down by supplier country.
    Used for market share and ranking calculations.

    This is a convenience function that calls fetch_market_imports_by_partner_batch for a single market.
    """
    result = fetch_market_imports_by_partner_batch([partner_code], hs_code, years)
    return result.drop(columns=['partner_code']) if not result.empty else pd.DataFrame(columns=['year', 'supplier', 'trade_value'])


def fetch_global_imports(hs_code: str, years: List[int], unified_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Fetch global import data for market size analysis using unified API call.

    This function extracts global rankings from the unified dataset.
    Uses partnerCode='0' (World aggregate) to get total imports per country.

    Parameters:
    -----------
    hs_code : str
        HS product code (6-digit)
    years : List[int]
        List of years to fetch data for
    unified_data : pd.DataFrame, optional
        Pre-fetched unified global data. If provided, skips API call.

    Returns:
    --------
    pd.DataFrame
        DataFrame with columns: partner, trade_value, year, rank
        Data is disaggregated by year (one record per country per year)
    """
    # Use provided unified data or fetch it
    if unified_data is not None:
        unified_data = unified_data.copy()
    else:
        unified_data = fetch_unified_global_imports(hs_code, years)

    if unified_data.empty:
        return pd.DataFrame(columns=['partner', 'trade_value', 'year'])

    # Extract world totals (partnerCode == '0' represents world aggregate)
    world_totals = unified_data[unified_data['partnerCode'] == '0'].copy()

    if world_totals.empty:
        logger.warning("No world totals found in unified data")
        return pd.DataFrame(columns=['partner', 'trade_value', 'year'])

    # Aggregate by importing country AND year (keep disaggregated)
    result = world_totals.groupby(['reporterCode', 'year'])['primaryValue'].sum().reset_index()
    result = result.rename(columns={'reporterCode': 'partner', 'primaryValue': 'trade_value'})

    # Filter to requested years only
    result = result[result['year'].isin(years)]

    if result.empty:
        logger.warning("❌ No import data found for requested years")
        return pd.DataFrame(columns=['partner', 'trade_value', 'year'])

    # Add rank per year
    result['rank'] = result.groupby('year')['trade_value'].rank(ascending=False, method='dense')

    # Sort by year, then by rank
    result = result.sort_values(['year', 'rank'])

    logger.info(f"🎯 Successfully identified {result['partner'].nunique()} global import markets across {len(result)} records")

    return result


def fetch_global_exports(hs_code: str, years: List[int]) -> pd.DataFrame:
    """
    Fetch global export data for price comparison.
    Uses simplified approach to minimize API calls.

    Parameters:
    -----------
    hs_code : str
        HS product code (6-digit)
    years : List[int]
        List of years to fetch data for

    Returns:
    --------
    pd.DataFrame
        DataFrame with columns: year, trade_value, trade_quantity
    """
    if COMTRADE_API_KEY is None:
        logger.warning("UN Comtrade API key not set")

    all_data = []
    hs_code_clean = hs_code.replace('.', '')

    # Simplified approach: Try to get "World" data (reporter code '000') first
    # If not available, fall back to major exporters
    years_str = ','.join(str(year) for year in years)

    # Try World data first (much more efficient)
    try:
        logger.info(f"Fetching global exports for HS {hs_code_clean} using World reporter")

        response = comtradeapicall.getFinalData(
                subscription_key=COMTRADE_API_KEY,
                typeCode='C',
                freqCode='A',
                clCode='HS',
                period=years_str,
                reporterCode='000',  # World
                cmdCode=hs_code_clean,
                flowCode='X',  # Export
                partnerCode=None,  # All partners
                partner2Code=None,
                customsCode=None,
                motCode=None
            )

        if response is not None and ((isinstance(response, pd.DataFrame) and not response.empty) or
                                    (isinstance(response, list) and len(response) > 0)):
            if isinstance(response, pd.DataFrame):
                df = response
            else:
                df = pd.DataFrame(response)

            # Process the data
            df['year'] = pd.to_numeric(df.get('period', df.get('year')), errors='coerce')
            df['trade_value'] = pd.to_numeric(df.get('primaryValue', df.get('trade_value')), errors='coerce')
            df['trade_quantity'] = pd.to_numeric(df.get('qty', df.get('trade_quantity')), errors='coerce')

            # Filter to our years of interest
            df = df[df['year'].isin(years)]
            df['partner'] = 'World'

            all_data.append(df)
            logger.info(f"Successfully retrieved World export data: {len(df)} records")
            return df  # Return early if World data works

    except Exception as e:
        logger.warning(f"World reporter data not available, falling back to major exporters: {e}")

    # Fallback: query major exporters (simplified to top 5)
    major_exporters = ['156', '842', '276', '392', '826']  # China, USA, Germany, Japan, UK (reduced from 10)

    for year in years:
        year_data = []
        
        for reporter_code in major_exporters:
            try:
                response = comtradeapicall.getFinalData(
                        subscription_key=COMTRADE_API_KEY,
                        typeCode='C',
                        freqCode='A',
                        clCode='HS',
                        period=str(year),
                        reporterCode=reporter_code,
                        cmdCode=hs_code_clean,
                        flowCode='X',  # Export
                        partnerCode=None,  # All partners
                        partner2Code=None,
                        customsCode=None,
                        motCode=None
                    )
                
                time.sleep(API_DELAY)
                
                if response is not None and len(response) > 0:
                    df = pd.DataFrame(response)
                    
                    # Sum all partners for this reporter
                    if 'tradeValue' in df.columns or 'primaryValue' in df.columns:
                        value_col = 'tradeValue' if 'tradeValue' in df.columns else 'primaryValue'
                        total_value = pd.to_numeric(df[value_col], errors='coerce').sum()
                    else:
                        total_value = 0
                    
                    if 'qty' in df.columns or 'netWgt' in df.columns:
                        qty_col = 'qty' if 'qty' in df.columns else 'netWgt'
                        total_quantity = pd.to_numeric(df[qty_col], errors='coerce').sum()
                    else:
                        total_quantity = None
                    
                    year_data.append({
                        'reporter': reporter_code,
                        'trade_value': total_value,
                        'trade_quantity': total_quantity
                    })
                    
            except Exception as e:
                logger.debug(f"Error fetching global export data for {reporter_code}, {hs_code_clean} in {year}: {e}")
                continue
        
        if year_data:
            year_df = pd.DataFrame(year_data)
            year_df['year'] = year
            all_data.append(year_df)
    
    if not all_data:
        return pd.DataFrame(columns=['year', 'trade_value', 'trade_quantity'])
    
    result = pd.concat(all_data, ignore_index=True)
    
    # Aggregate by year (sum across all reporters)
    if len(result) > 0:
        global_agg = result.groupby('year').agg({
            'trade_value': 'sum',
            'trade_quantity': 'sum'
        }).reset_index()
        return global_agg
    
    return pd.DataFrame(columns=['year', 'trade_value', 'trade_quantity'])
