#!/usr/bin/env python3
import json

# Read the JSON files
with open('output/results_detailed.json', 'r') as f:
    trade_data = json.load(f)

with open('indicator_definitions.json', 'r') as f:
    definitions = json.load(f)

# HTML template with embedded data
html_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Afghanistan Trade Intelligence Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --undp-blue: #009EDB;
            --undp-dark-blue: #002D5C;
            --undp-light-blue: #A3D7E8;
            --undp-gray: #F2F2F2;
            --undp-dark-gray: #666666;
            --white: #FFFFFF;
        }
        body { font-family: Arial, sans-serif; margin: 0; background: var(--undp-gray); }
        .header { background: linear-gradient(135deg, var(--undp-blue), var(--undp-dark-blue)); color: white; padding: 1rem 0; position: relative; }
        .header .container { display: flex; align-items: center; justify-content: center; position: relative; }
        .header h1 { margin: 0; font-size: 2rem; }
        .header p { margin: 0.5rem 0 0 0; font-size: 1rem; opacity: 0.9; }
        .header-logo { position: absolute; left: 2rem; top: 50%; transform: translateY(-50%); height: 100px; width: auto; }
        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
        .product-selector { background: white; padding: 2rem; border-radius: 10px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); margin-bottom: 2rem; }
        .product-buttons { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 2rem; }
        .product-btn { background: var(--undp-light-blue); color: var(--undp-dark-blue); border: 2px solid var(--undp-blue); padding: 0.75rem 1.5rem; border-radius: 8px; cursor: pointer; font-weight: 600; transition: all 0.3s ease; }
        .product-btn:hover, .product-btn.active { background: var(--undp-blue); color: white; }
        .chart-container { background: white; padding: 1rem; border-radius: 10px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); position: relative; height: 400px; display: flex; flex-direction: column; }
        .chart-container .chart-header { margin-bottom: 0.5rem; }
        .chart-container canvas { width: 100% !important; height: calc(100% - 2rem) !important; }
        .chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
        .chart-title { margin: 0; font-size: 1.3rem; color: var(--undp-dark-blue); }
        .info-icon { cursor: help; color: var(--undp-blue); font-size: 1.2rem; padding: 0.25rem; border-radius: 50%; transition: background-color 0.3s; }
        .info-icon:hover { background-color: var(--undp-light-blue); }
        .tooltip { display: none; position: absolute; background: var(--undp-dark-blue); color: white; padding: 1rem; border-radius: 8px; max-width: 300px; z-index: 1000; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3); font-size: 0.9rem; line-height: 1.4; top: 100%; right: 0; margin-top: 0.5rem; }
        .tooltip.show { display: block; }
        .tooltip strong { display: block; margin-bottom: 0.5rem; color: var(--undp-light-blue); }
        .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 2rem; }
        .markets-table { background: white; border-radius: 10px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); overflow: hidden; margin-bottom: 2rem; }
        .markets-table h3 { background: var(--undp-blue); color: white; padding: 1.5rem; margin: 0; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 1rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: var(--undp-light-blue); color: var(--undp-dark-blue); font-weight: 600; }
        .rank-badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
        .rank-1 { background: #ffd700; color: #000; }
        .rank-2 { background: #c0c0c0; color: #000; }
        .rank-3 { background: #cd7f32; color: #000; }
        .rank-top10 { background: var(--undp-light-blue); color: var(--undp-dark-blue); }
        .competitiveness-badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
        .highly-competitive { background: #28a745; color: white; }
        .competitive { background: #17a2b8; color: white; }
        .average { background: #ffc107; color: #000; }
        .above-market { background: #fd7e14; color: white; }
        .premium { background: #dc3545; color: white; }
        .growth-positive { color: #28a745; }
        .growth-negative { color: #dc3545; }
        .loading { text-align: center; padding: 3rem; color: var(--undp-dark-gray); }
        .no-data { text-align: center; padding: 2rem; color: var(--undp-dark-gray); font-style: italic; }
        @media (max-width: 768px) { .dashboard-grid { grid-template-columns: 1fr; } .product-buttons { justify-content: center; } .product-btn { flex: 1 1 100%; text-align: center; } }
    </style>
</head>
<body>
    <header class="header">
        <div class="container">
            <img src="undp_logo.png" alt="UNDP Logo" class="header-logo">
            <div>
                <h1>🇦🇫 Afghanistan Trade Intelligence Dashboard</h1>
                <p>UNDP - Market Intelligence for Afghan Exports</p>
            </div>
        </div>
    </header>

    <div class="container">
        <div class="product-selector">
            <h2>Select Product to Analyze</h2>
            <div id="product-buttons" class="product-buttons"></div>
        </div>

        <div id="dashboard-content" style="display: none;">
            <div class="dashboard-grid">
                <div class="chart-container">
                    <div class="chart-header">
                        <h3 class="chart-title">Top Global Importers</h3>
                        <span class="info-icon" data-indicator="global_market_size">ℹ️</span>
                    </div>
                    <div class="tooltip" id="tooltip-global_market_size">
                        <strong>Global Market Size (2024)</strong>
                        Total value of all countries' imports of this product globally in the latest year (2024). Shows the largest import markets worldwide, ranked by total import value in billions.
                    </div>
                    <canvas id="topImportersChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-header">
                        <h3 class="chart-title">Import Growth Rates (CAGR)</h3>
                        <span class="info-icon" data-indicator="cagr_pct">ℹ️</span>
                    </div>
                    <div class="tooltip" id="tooltip-cagr_pct">
                        <strong>Compound Annual Growth Rate</strong>
                        The geometric progression ratio that provides a constant rate of return over the time period. Calculated as: ((Ending Value / Beginning Value)^(1/number of periods)) - 1) × 100.
                    </div>
                    <canvas id="growthChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-header">
                        <h3 class="chart-title">Afghanistan Export Value by Market</h3>
                        <span class="info-icon" data-indicator="export_value">ℹ️</span>
                    </div>
                    <div class="tooltip" id="tooltip-export_value">
                        <strong>Afghanistan Export Value (2024)</strong>
                        Total value of Afghanistan's exports to this specific market in USD for the latest year (2024). Sum of trade values for all HS codes in the latest year (2024).
                    </div>
                    <canvas id="exportValueChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-header">
                        <h3 class="chart-title">Afghanistan Market Share</h3>
                        <span class="info-icon" data-indicator="market_share_pct">ℹ️</span>
                    </div>
                    <div class="tooltip" id="tooltip-market_share_pct">
                        <strong>Market Share Percentage (2024)</strong>
                        Afghanistan's share of the total imports in this market for the latest year (2024). Calculated as: (Afghanistan's exports to market in 2024 / Total market imports in 2024) × 100
                    </div>
                    <canvas id="marketShareChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-header">
                        <h3 class="chart-title">Afghanistan Pricing Competitiveness</h3>
                        <span class="info-icon" data-indicator="price_competitiveness">ℹ️</span>
                    </div>
                    <div class="tooltip" id="tooltip-price_competitiveness">
                        <strong>Price Competitiveness</strong>
                        Categorical assessment of Afghanistan's pricing strategy based on price_vs_market_pct thresholds: Highly Competitive (Price > 20% below market), Competitive (10-20% below), Average (±10%), Above Market (10-20% above), Premium (>20% above).
                    </div>
                    <canvas id="pricingChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-header">
                        <h3 class="chart-title">Market Opportunity Matrix</h3>
                        <span class="info-icon" data-indicator="market_rank">ℹ️</span>
                    </div>
                    <div class="tooltip" id="tooltip-market_rank">
                        <strong>Market Rank</strong>
                        Afghanistan's ranking among all suppliers to this market by export value. Ranking based on export value compared to all other countries exporting to this market (1 = highest).
                    </div>
                    <canvas id="opportunityChart" width="400" height="300"></canvas>
                </div>
            </div>

            <div class="markets-table">
                <h3>Detailed Market Analysis</h3>
                <div style="overflow-x: auto;">
                    <table id="markets-table">
                        <thead><tr><th>Rank</th><th>Market</th><th>Export Value</th><th>Market Size</th><th>Market Share</th><th>CAGR</th><th>Unit Price</th><th>Competitiveness</th></tr></thead>
                        <tbody id="markets-table-body"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Embedded data
        const tradeData = {TRADE_DATA_PLACEHOLDER};
        const indicatorDefinitions = {DEFINITIONS_PLACEHOLDER};

        let currentProduct = null;
        let charts = {};

        // Tooltip functionality
        document.addEventListener('click', function(e) {
            if (e.target.classList.contains('info-icon')) {
                const indicator = e.target.dataset.indicator;
                const tooltip = document.getElementById('tooltip-' + indicator);
                // Hide all tooltips first
                document.querySelectorAll('.tooltip').forEach(t => t.classList.remove('show'));
                // Show the clicked tooltip
                if (tooltip) {
                    tooltip.classList.add('show');
                }
            } else {
                // Hide tooltips when clicking elsewhere
                document.querySelectorAll('.tooltip').forEach(t => t.classList.remove('show'));
            }
        });

        // Initialize dashboard
        document.addEventListener('DOMContentLoaded', function() {
            initializeDashboard();
        });

        function initializeDashboard() {
            // Create product buttons
            const productButtons = document.getElementById('product-buttons');
            tradeData.products.forEach(product => {
                if (product.status === 'success') {
                    const button = document.createElement('button');
                    button.className = 'product-btn';
                    button.textContent = product.product;
                    button.onclick = () => selectProduct(product.product);
                    productButtons.appendChild(button);
                }
            });

            // Auto-select first product
            const firstProduct = tradeData.products.find(p => p.status === 'success');
            if (firstProduct) {
                selectProduct(firstProduct.product);
            }
        }

        function selectProduct(productName) {
            currentProduct = tradeData.products.find(p => p.product === productName);
            if (!currentProduct) return;

            // Update button states
            document.querySelectorAll('.product-btn').forEach(btn => {
                btn.classList.toggle('active', btn.textContent === productName);
            });

            // Show dashboard content
            document.getElementById('dashboard-content').style.display = 'block';

            // Update all charts and tables
            updateDashboard();
        }

        function updateDashboard() {
            updateMarketShareChart();
            updateExportValueChart();
            updateGrowthChart();
            updateTopImportersChart();
            updatePricingChart();
            updateOpportunityChart();
            updateMarketsTable();
        }

        function updateMarketShareChart() {
            const ctx = document.getElementById('marketShareChart').getContext('2d');
            if (charts.marketShare) charts.marketShare.destroy();

            const markets = currentProduct.markets.filter(m => m.market_share && m.market_share > 0);
            const sortedMarkets = markets.sort((a, b) => b.market_share - a.market_share);
            const data = {
                labels: sortedMarkets.map(m => m.market_name),
                datasets: [{
                    label: 'Market Share (%)',
                    data: sortedMarkets.map(m => m.market_share),
                    backgroundColor: 'rgba(0, 158, 219, 0.8)',
                    borderColor: 'rgba(0, 158, 219, 1)',
                    borderWidth: 1
                }]
            };

            charts.marketShare = new Chart(ctx, {
                type: 'bar',
                data: data,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    layout: { padding: { top: 10, bottom: 10, left: 10, right: 10 } },
                    plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, ticks: { callback: v => v + '%' } } }
                }
            });
        }

        function updateExportValueChart() {
            const ctx = document.getElementById('exportValueChart').getContext('2d');
            if (charts.exportValue) charts.exportValue.destroy();

            const markets = currentProduct.markets.filter(m => m.export_value > 0);
            const sortedMarkets = markets.sort((a, b) => b.export_value - a.export_value);
            const data = {
                labels: sortedMarkets.map(m => m.market_name),
                datasets: [{
                    label: 'Afghanistan Export Value (USD)',
                    data: sortedMarkets.map(m => m.export_value),
                    backgroundColor: 'rgba(0, 45, 92, 0.8)',
                    borderColor: 'rgba(0, 45, 92, 1)',
                    borderWidth: 1
                }]
            };

            charts.exportValue = new Chart(ctx, {
                type: 'bar',
                data: data,
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    layout: { padding: { top: 10, bottom: 10, left: 10, right: 10 } },
                    plugins: { legend: { display: false } },
                    scales: { x: { ticks: { callback: v => '$' + (v / 1000000).toFixed(1) + 'M' } } }
                }
            });
        }

        function updateGrowthChart() {
            const ctx = document.getElementById('growthChart').getContext('2d');
            if (charts.growth) charts.growth.destroy();

            const markets = currentProduct.markets.filter(m => m.growth_rate && m.growth_rate.cagr !== null);
            const sortedMarkets = markets.sort((a, b) => b.growth_rate.cagr - a.growth_rate.cagr);
            const data = {
                labels: sortedMarkets.map(m => m.market_name),
                datasets: [{
                    label: 'CAGR (%)',
                    data: sortedMarkets.map(m => m.growth_rate.cagr),
                    backgroundColor: sortedMarkets.map(m => m.growth_rate.cagr >= 0 ? 'rgba(40, 167, 69, 0.8)' : 'rgba(220, 53, 69, 0.8)'),
                    borderColor: sortedMarkets.map(m => m.growth_rate.cagr >= 0 ? 'rgba(40, 167, 69, 1)' : 'rgba(220, 53, 69, 1)'),
                    borderWidth: 1
                }]
            };

            charts.growth = new Chart(ctx, {
                type: 'bar',
                data: data,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    layout: { padding: { top: 10, bottom: 10, left: 10, right: 10 } },
                    plugins: { legend: { display: false } },
                    scales: { y: { ticks: { callback: v => v + '%' } } }
                }
            });
        }

        function updateTopImportersChart() {
            const ctx = document.getElementById('topImportersChart').getContext('2d');
            if (charts.topImporters) charts.topImporters.destroy();

            // Filter markets with valid data and sort by global market size (largest importers first)
            const validMarkets = currentProduct.markets.filter(m => m.global_market_size && m.global_market_size > 0);
            const markets = [...validMarkets].sort((a, b) => b.global_market_size - a.global_market_size);
            const topMarkets = markets.slice(0, 10); // Top 10 largest importers (already sorted)

            if (topMarkets.length === 0) {
                ctx.font = '14px Arial';
                ctx.fillStyle = '#666';
                ctx.textAlign = 'center';
                ctx.fillText('No data available for this product', ctx.canvas.width / 2, ctx.canvas.height / 2);
                return;
            }

            const data = {
                labels: topMarkets.map(m => m.market_name),
                datasets: [{
                    label: 'Global Import Value (USD)',
                    data: topMarkets.map(m => m.global_market_size),
                    backgroundColor: 'rgba(0, 158, 219, 0.8)',
                    borderColor: 'rgba(0, 158, 219, 1)',
                    borderWidth: 1
                }]
            };

            charts.topImporters = new Chart(ctx, {
                type: 'bar',
                data: data,
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    layout: { padding: { top: 10, bottom: 10, left: 10, right: 10 } },
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            ticks: {
                                callback: function(value) {
                                    return '$' + (value / 1000000000).toFixed(1) + 'B';
                                }
                            }
                        }
                    }
                }
            });
        }

        function updatePricingChart() {
            const ctx = document.getElementById('pricingChart').getContext('2d');
            if (charts.pricing) charts.pricing.destroy();

            const markets = currentProduct.markets.filter(m =>
                m.market_price_comparison &&
                m.market_price_comparison.competitiveness &&
                m.market_price_comparison.competitiveness.trim() !== ''
            );

            if (markets.length === 0) {
                ctx.font = '14px Arial';
                ctx.fillStyle = '#666';
                ctx.textAlign = 'center';
                ctx.fillText('No pricing data available for this product', ctx.canvas.width / 2, ctx.canvas.height / 2);
                return;
            }

            const competitivenessCounts = {};
            markets.forEach(m => {
                const comp = m.market_price_comparison.competitiveness;
                competitivenessCounts[comp] = (competitivenessCounts[comp] || 0) + 1;
            });

            const data = {
                labels: Object.keys(competitivenessCounts),
                datasets: [{
                    data: Object.values(competitivenessCounts),
                    backgroundColor: ['rgba(40, 167, 69, 0.8)', 'rgba(23, 162, 184, 0.8)', 'rgba(255, 193, 7, 0.8)', 'rgba(253, 126, 20, 0.8)', 'rgba(220, 53, 69, 0.8)'],
                    borderColor: ['rgba(40, 167, 69, 1)', 'rgba(23, 162, 184, 1)', 'rgba(255, 193, 7, 1)', 'rgba(253, 126, 20, 1)', 'rgba(220, 53, 69, 1)'],
                    borderWidth: 1
                }]
            };

            charts.pricing = new Chart(ctx, {
                type: 'doughnut',
                data: data,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    layout: { padding: { top: 10, bottom: 10, left: 10, right: 10 } },
                    plugins: { legend: { position: 'bottom' } }
                }
            });
        }

        function updateOpportunityChart() {
            const ctx = document.getElementById('opportunityChart').getContext('2d');
            if (charts.opportunity) charts.opportunity.destroy();

            const markets = currentProduct.markets.filter(m =>
                m.export_value > 0 &&
                m.global_market_size > 0 &&
                m.market_share !== null &&
                m.market_share !== undefined &&
                !isNaN(m.market_share)
            );

            if (markets.length === 0) {
                ctx.font = '14px Arial';
                ctx.fillStyle = '#666';
                ctx.textAlign = 'center';
                ctx.fillText('No opportunity data available for this product', ctx.canvas.width / 2, ctx.canvas.height / 2);
                return;
            }

            const data = {
                datasets: [{
                    label: 'Market Opportunities',
                    data: markets.map(m => ({
                        x: Math.log10(m.global_market_size),
                        y: m.market_share,
                        r: Math.sqrt(m.export_value) / 500
                    })),
                    backgroundColor: 'rgba(0, 158, 219, 0.6)',
                    borderColor: 'rgba(0, 158, 219, 1)',
                    borderWidth: 1
                }]
            };

            charts.opportunity = new Chart(ctx, {
                type: 'bubble',
                data: { labels: markets.map(m => m.market_name), datasets: data.datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    layout: { padding: { top: 10, bottom: 10, left: 10, right: 10 } },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    const market = markets[ctx.dataIndex];
                                    return [
                                        market.market_name,
                                        `Market Size: $${(market.global_market_size / 1000000).toFixed(1)}M`,
                                        `Share: ${(market.market_share).toFixed(2)}%`,
                                        `Exports: $${(market.export_value / 1000000).toFixed(1)}M`
                                    ];
                                }
                            }
                        }
                    },
                    scales: {
                        x: { title: { display: true, text: 'Market Size' }, ticks: { callback: v => '$' + (Math.pow(10, v) / 1000000000).toFixed(1) + 'B' } },
                        y: { title: { display: true, text: 'Market Share (%)' }, beginAtZero: true }
                    }
                }
            });
        }

        function updateMarketsTable() {
            const tbody = document.getElementById('markets-table-body');
            tbody.innerHTML = '';

            if (!currentProduct.markets || currentProduct.markets.length === 0) {
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="8" style="text-align: center; padding: 2rem; color: #666;">No market data available for this product</td>';
                tbody.appendChild(row);
                return;
            }

            currentProduct.markets.forEach(market => {
                const row = document.createElement('tr');
                const rankClass = market.rank && market.rank <= 3 ? `rank-${market.rank}` : 'rank-top10';
                const competitiveness = market.market_price_comparison && market.market_price_comparison.competitiveness ?
                    market.market_price_comparison.competitiveness : null;

                row.innerHTML = `
                    <td><span class="rank-badge ${rankClass}">#${market.rank || '-'}</span></td>
                    <td>${market.market_name || 'Unknown'}</td>
                    <td>${market.export_value && market.export_value > 0 ? formatCurrency(market.export_value) : '-'}</td>
                    <td>${market.global_market_size ? formatCurrency(market.global_market_size) : '-'}</td>
                    <td>${market.market_share !== null && market.market_share !== undefined ? market.market_share.toFixed(2) + '%' : '-'}</td>
                    <td class="${market.growth_rate && market.growth_rate.cagr !== null && market.growth_rate.cagr >= 0 ? 'growth-positive' : 'growth-negative'}">
                        ${market.growth_rate && market.growth_rate.cagr !== null ? market.growth_rate.cagr.toFixed(1) + '%' : '-'}
                    </td>
                    <td>${market.unit_price ? '$' + market.unit_price.toFixed(2) : '-'}</td>
                    <td>${competitiveness ? `<span class="competitiveness-badge ${getCompetitivenessClass(competitiveness)}">${competitiveness}</span>` : '-'}</td>
                `;
                tbody.appendChild(row);
            });
        }

        function getCompetitivenessClass(competitiveness) {
            const classes = { 'Highly Competitive': 'highly-competitive', 'Competitive': 'competitive', 'Average': 'average', 'Above Market': 'above-market', 'Premium': 'premium' };
            return classes[competitiveness] || 'average';
        }

        function formatCurrency(value) {
            if (value >= 1000000) return '$' + (value / 1000000).toFixed(1) + 'M';
            else if (value >= 1000) return '$' + (value / 1000).toFixed(1) + 'K';
            return '$' + value.toFixed(0);
        }
    </script>
</body>
</html>'''

# Replace placeholders with actual data
html_content = html_template.replace('{TRADE_DATA_PLACEHOLDER}', json.dumps(trade_data))
html_content = html_content.replace('{DEFINITIONS_PLACEHOLDER}', json.dumps(definitions))

# Write the standalone HTML file
with open('docs/dashboard_standalone.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print('Standalone dashboard updated: docs/dashboard_standalone.html')