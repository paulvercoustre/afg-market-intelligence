# Afghanistan Trade Intelligence Tool

A comprehensive market intelligence platform for analyzing Afghanistan's export performance across key agricultural and manufactured products. Built for UNDP to support evidence-based trade policy and economic development strategies.

## Overview

This tool analyzes Afghanistan's key export products using data from the UN Comtrade API for granular trade data. The tool provides detailed market intelligence by analyzing each HS code separately for precise insights.

- **Target Products**: 9 individual HS codes across major Afghan export categories
- **Separated Analysis**: Each HS code is analyzed independently to avoid aggregated distortions
- **Key Indicators**:
  - Largest markets for each specific HS code
  - Growth rates for top markets (past 4 years: 2021-2024)
  - Market share of Afghanistan and competitor analysis
  - Price competitiveness (FOB value/volume) vs global average and top competitors

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Setup API Key

You need a UN Comtrade API subscription key. Get one from: https://unstats.un.org/wiki/display/comtrade/UN+Comtrade+API

Set it as an environment variable:
```bash
export COMTRADE_API_KEY="your_api_key_here"
```

Or set it in your code:
```python
from comtrade_client import set_api_key
set_api_key("your_api_key_here")
```

### Test API Connectivity

Test the UN Comtrade API connectivity:

```bash
python test_api.py
```

This will verify that you can access the UN Comtrade API and retrieve data.

### Run Full Analysis

Run the main analysis:

```bash
python main.py
```

Results will be saved in the `output/` directory:
- `results_summary.csv`: Summary table with all indicators per product-market combination
- `results_detailed.json`: Detailed results with full data including growth rates, competitor shares, etc.

## Interactive Dashboard

The project includes a comprehensive self-contained web dashboard for visualizing trade intelligence data.

### Dashboard Features

- **9 Individual HS Code Products**: Almonds, Saffron, Grapes, Carpets, Cashmere (each analyzed separately)
- **6 Interactive Charts**: Market share, export values, growth rates, pricing competitiveness, top importers, opportunity matrix
- **Strategic Layout**: Top Global Importers positioned prominently in top-left for immediate market context
- **Professional Design**: UNDP branded with clean, responsive interface
- **Detailed Tooltips**: Click ℹ️ icons for comprehensive metric definitions
- **Sorted Data**: All bar charts sorted descending for easy analysis
- **Offline Ready**: Self-contained HTML with embedded data (no web server required)

### Using the Dashboard

1. **Open Dashboard**: Double-click `dashboard/dashboard_standalone.html` in any web browser
2. **Select Product**: Choose from 9 individual HS code products in the dropdown
3. **Explore Data**: All charts and tables update automatically
4. **Get Details**: Click ℹ️ icons for metric explanations
5. **Analyze Trends**: Review sorted bar charts and market opportunities

### Regenerating the Dashboard

After running new analysis:

```bash
python3 create_standalone_dashboard.py
```

This embeds the latest data into the dashboard for offline use.

## Quick Start

### For Analysis
```bash
# Install dependencies
pip install -r requirements.txt

# Set API key (get from UN Comtrade)
export COMTRADE_API_KEY="your_api_key_here"

# Run analysis
python main.py

# Generate updated dashboard
python3 create_standalone_dashboard.py
```

### For Dashboard Only
```bash
# Just open the dashboard (works offline)
open dashboard/dashboard_standalone.html
```

## License & Attribution

Built for UNDP Afghanistan by [Your Organization]. Uses data from UN Comtrade API. Dashboard visualizations powered by Chart.js.

## Project Structure

```
afghanistan-trade-intelligence/
├── README.md                    # Project documentation
├── requirements.txt            # Python dependencies
├── .gitignore                  # Git ignore rules
├── config.py                   # Product definitions and HS codes
├── comtrade_client.py          # UN Comtrade API client
├── indicators.py               # Trade indicator calculations
├── main.py                     # Main analysis pipeline
├── create_standalone_dashboard.py  # Dashboard generator
├── dashboard/
│   ├── dashboard_standalone.html   # Self-contained interactive dashboard
│   ├── undp_logo.png              # UNDP branding assets
│   └── info_tooltip.jpg           # Tooltip icon
├── indicator_definitions.json  # Metric definitions and tooltips
└── output/                    # Analysis results (sample data included)
    ├── results_detailed.json  # Detailed analysis results
    └── results_summary.csv    # Summary export data
```

## Data Sources & Methodology

### Data Sources
- **UN Comtrade API**: Primary source for global trade statistics with 6-digit HS codes
- **Mirror Statistics**: Afghanistan export data derived from partner countries' import records
- **Analysis Period**: 2021-2024 (4-year trend analysis for robust growth calculations)

### Analytical Approach
- **Individual HS Code Analysis**: Each 6-digit HS code analyzed separately to avoid aggregation distortions
- **Comprehensive Market Coverage**: Top 10 global import markets per HS code
- **Multi-Metric Intelligence**: 12+ indicators including market share, growth rates, pricing competitiveness
- **Competitive Intelligence**: Comparison with top global suppliers in each market

### Key Indicators Calculated
- Export values and market shares
- Year-over-year and compound annual growth rates
- Unit pricing and competitiveness analysis
- Market ranking and competitive positioning
- Global market size and opportunity assessment

## Notes

- **HS Code Format**: UN Comtrade accepts HS codes in various formats (e.g., 080211 or 0802.11)
- **Data Availability**: Some years/products may have missing data - the tool handles this gracefully with warnings
- **API Rate Limits**: Delays are included between API requests to respect rate limits
- **Quantity Data**: Some indicators (like unit price) require quantity data, which may not always be available
- **Market Share Calculations**: Requires fetching total import data for each market, which may take time
- **Competitor Analysis**: Price comparisons with competitors may be limited if quantity data is not available

## Output Format

### Summary CSV (`results_summary.csv`)
Contains one row per product-market combination with:
- Product name and market code
- Export value and market rank
- Market share percentage
- Afghanistan's rank among suppliers
- Growth rates (YoY, CAGR)
- Unit price and comparisons to global average and competitors

### Detailed JSON (`results_detailed.json`)
Contains full analysis results including:
- Complete growth rate breakdowns
- Competitor market shares
- Detailed price competitiveness metrics
- All raw data used in calculations

## Interactive Dashboard

The project includes a comprehensive web-based dashboard for visualizing trade intelligence data.

### Features

- **Product-Oriented Analysis**: Select from 9 individual HS code products
- **UNDP Design System**: Professional styling using official UNDP colors and logo
- **Interactive Tooltips**: Click ℹ️ icons for detailed metric definitions
- **Strategic Dashboard Layout**:
  - **Top Row**: **🗺️ Top Global Importers** (biggest markets) | Growth Rates (CAGR) | Afghanistan Export Values (current performance)
  - **Bottom Row**: Market share distribution, pricing competitiveness, and market opportunity matrix (detailed insights)
- **Multiple Visualizations**:
  - **🗺️ Top Global Importers** (top-left - shows largest import markets worldwide in single color)
  - **📈 Import Growth Rates (CAGR)** (performance trends, sorted descending)
  - **💰 Afghanistan Export Value by Market** (current export distribution, sorted descending)
  - **📊 Afghanistan Market Share** (penetration analysis, sorted descending)
  - **💵 Afghanistan Pricing Competitiveness** (competitive positioning)
  - **🎯 Market Opportunity Matrix** (strategic opportunities with larger, more visible bubbles)
- **Detailed Data Tables**: Comprehensive market-by-market analysis
- **Full-Tile Charts**: All visualizations fill their containers completely with proper padding for maximum data visibility
- **Instant Rendering**: Charts load instantly without expansion animations for professional presentation
- **Precise Layout**: Charts are perfectly contained within tile boundaries with no overflow
- **Responsive Design**: Works on desktop and mobile devices

### Accessing the Dashboard

#### Option 1: Standalone Dashboard (Recommended)
1. Run `python3 create_standalone_dashboard.py` to generate a self-contained dashboard
2. Open `dashboard/dashboard_standalone.html` in any web browser (works offline)
3. Select a product to explore its market intelligence

#### Option 2: Web Server Dashboard
1. Ensure analysis results exist in `output/results_detailed.json`
2. Start a local web server: `python3 -m http.server 8000`
3. Open `http://localhost:8000/dashboard_example.html` in a web browser
4. Select a product to explore its market intelligence

### Dashboard Files

- `dashboard/dashboard_standalone.html`: Self-contained dashboard (recommended for offline use)
- `dashboard_example.html`: Web server version (requires local server)
- `create_standalone_dashboard.py`: Script to generate the standalone version
- `indicator_definitions.json`: Metric definitions and descriptions

### Current Product Coverage

The tool analyzes 9 individual HS codes for precise market intelligence:

- **Almonds**: 080211 (In-shell), 080212 (Shelled)
- **Saffron**: 091020
- **Grapes**: 080610 (Fresh), 080620 (Dried/Raisins)
- **Carpets**: 570110 (Knotted), 570210 (Woven)
- **Cashmere**: 510211 (Raw hair), 611012 (Sweaters)

**Dashboard Layout Strategy:**
- **🎯 Top Global Importers** is prominently positioned in TOP LEFT as the first chart users see
- Clean single-color bars show the largest markets worldwide, setting the strategic context
- Uniform blue coloring focuses attention on market size rather than Afghanistan's current position
- Users instantly understand which countries represent the biggest global opportunities

Each HS code is analyzed separately to provide accurate, undistorted market insights.

### Key Metrics Displayed

The dashboard visualizes all 12+ calculated indicators including:
- **Afghanistan Export Values**: Current export values to each market
- **Global Market Sizes**: Total import values for largest global markets
- **Market Share Percentages**: Afghanistan's penetration in each market (displayed correctly as percentages)
- **Growth Rates**: CAGR and YoY growth trends
- **Price Competitiveness**: Competitive positioning vs. market averages
- **Market Rankings**: Afghanistan's position among suppliers
- **Top Global Importers**: Largest import markets worldwide (with Afghanistan's markets highlighted)

## Data Quality Notes

- **Mirror Statistics**: Afghanistan export data derived from partner countries' import records
- **Multi-HS Code Aggregation**: Products analyzed across multiple related HS codes
- **4-Year Analysis Period**: 2021-2024 for robust trend analysis
- **Top 10 Markets**: Focus on most important global markets per product
