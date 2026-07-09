# Market Intelligence Tool — Scoping Note

> **About this note:** This scoping note defines why we are building the Market Intelligence Tool, who it serves, and what is in and out of scope for the pilot. It is the reference point for the more detailed documents that follow — the functional specification, the data specification — and the basis for co-design with ACCI.
>
> Source: `Market Intelligence Tool- Scoping Note.docx` (converted to Markdown 2026-07-09).

## Background and Rationale

### The operating environment and Afghanistan trade context

International trade remains a critical driver of economic growth and a key pathway for Afghanistan to reduce its dependence on aid[^1]. Yet the operating environment has deteriorated markedly: the continued closure of the Pakistan border, compounded by regional instability in the Middle East, has disrupted established trade routes, increased logistical costs, and forced traders to pivot toward Iran, China, and Central Asian partners[^2], a shift expected to widen the trade deficit through FY2027. These pressures are reflected in a sharp contraction in export performance recorded in March 2026[^3], which reveals constraints in market access and execution rather than weakening demand, as several agricultural categories continued to grow[^4].

Recent trade statistics show that Afghanistan's exports remained concentrated in regional markets, with Pakistan and India accounting for the majority of exports[^5]. This persistent dependence on a narrow set of markets highlights the need for diversification in Afghanistan's export strategy to reinforce long-term trade resilience. Afghanistan retains clear comparative advantages in its agricultural and natural product base and unlocking this potential will require targeted action across quality and standards, export and investment promotion, cross-border trade facilitation, and inclusive value chain development[^6]. Based on these needs, the MSME Support Center serves as a one-stop platform designed to strengthen the export readiness, value added, and institutional resilience of MSMEs in Afghanistan with its three core service pillars structure: Value Chain Development, Trade Facilitation, and Access to Finance.

### Rationale for the Market Intelligence Tool

Aggregate trade statistics mask significant variation across products, corridors, and traders, and Afghanistan's trade ecosystem is no exception. Consultations with ACIM and ACCI confirmed the absence of structured intelligence tools, with both institutions noting persistent difficulties in tracking consumer trends and identifying high-potential markets and geographies[^7]. Survey findings from 500 MSMEs reinforce this picture: 81 percent cited weak buyer connections and market linkages as a key challenge; 60 percent identified the lack of market information, technical guidance, and advisory services as a binding constraint; 68 percent of almond MSMEs reported low traceability and unreliable supply chains; 35 percent flagged certification gaps; and only 12 percent currently use structured market reports[^8]. These gaps are not incidental, they reflect a systemic absence of accessible, actionable trade intelligence that leaves exporters, producers, and MSMEs navigating complex markets without adequate information or support.

To bridge this gap, under the Trade Facilitation pillar of the MSME Support Centre that equips MSMEs to access markets by building practical export and trade capabilities, the Market Intelligence Tool has been designed. The Market Intelligence Tool is a data-driven trade dashboard that consolidates trade data and market insights into a single platform. Responding to the intelligence needs of Afghan MSMEs, exporters, investors, and chambers of commerce, the tool functions as a diagnostic and descriptive instrument providing evidence-based insights to inform trade strategies, diversify export partners and mitigate concentration risks and MSME growth efforts across Afghanistan. It offers a structured framework to monitor, analyze, and profile market opportunities using key trade indicators, responding directly to the needs MSMEs themselves identified: timely data on trade flows, demand trends, pricing and competition, market access conditions including tariffs and certifications, and connections to buyers in international markets. By operationalizing this evidence-based approach, the tool aims to empower Afghan traders, exporters, producers, and international partners to design tailored market entry and export strategies that are proactive, actionable, and impactful.

## Objectives

### General Objective

The Market Intelligence Tool aims to systematically track, collect, analyze, and disseminate actionable intelligence on markets, competitors, products, and customers **to strengthen the export competitiveness of Afghanistan's private sector**. Institutionalized within the MSME Support Centre, the Tool equips trade actors and partners with the information needed to make informed decisions on market expansion and to identify markets with untapped growth potential.

### Specific Objectives

- Enhance **export competitiveness** of Afghan MSMEs by providing regular, actionable market intelligence.
- Improve the ability for the **private sector to use market intelligence** and opportunity scanning.
- Help Afghan chambers set up a trade **intelligence service system**.
- Train MSME Support Centre staff to **independently manage data tools**, generate regular market briefs, and advise MSMEs on export opportunities.

## Users and Use Cases

The tool is designed primarily for:

- **Afghan MSMEs and exporters**: producers, processors, and traders seeking market intelligence to identify buyers and make export decisions.

Other user groups include:

- **Trade Information Officers at ACCI and chambers of commerce**: staff who use the tool to track trade trends in one platform and advise member businesses.
- **International buyers and investors**: foreign importers and investors sourcing Afghan products or assessing entry into the Afghan market.
- **Development partners and donors**: organizations such as UNDP, ITC, and the World Bank that use the tool to monitor trade performance and target technical assistance.

### Use Cases

**Use Case 1: The Composite Score Engine**

- **User:** Ready-to-export Afghan MSMEs.
- **User question:** Which destination market offers the highest reward and lowest risk for my specific product overall?
- **How it works:** User can consult the composite score that aggregates performance metrics (growth, pricing, and route reliability) into a single, easy-to-digest ranking.

**Use Case 2: Logistics, Route Optimization, and Trade Compliance**

- **User:** Logistics Coordinators.
- **User question:** What are the freight costs, lead times, and documentation requirements for major export routes, and which corridors are most actively used?
- **How it works:** User can analyze active trade corridors to compare current shipping costs and transit times, while accessing a clear breakdown of required customs documentation to avoid costly border delays.

## Features and Scope

The tool is equipped with features designed around the following trade topics: Training, Trade Analysis, Scoring, Buyer Identification and KYC, Logistics, Competition, Reducing Risks (Political and Administrative, Economic and Transactional, Pricing).

**Geographic scope:** The tool covers Afghanistan as the primary country of origin.

**Product scope:** The pilot covers 34 Afghan export products spanning tree nuts, spices and herbs, dried and fresh fruits, carpets and textiles, luxury fibers, minerals, and oilseeds, with the architecture designed to expand to additional product categories as the tool matures.

**Thematic scope:** The tool covers five core intelligence domains: market opportunity dimensions, export value chain stages, risk and enabler categories, trade intelligence pillars, and sectoral and product themes.

### Tool Features

Phases: 1 = Core, 2 = Intermediate, 3 = Advanced.

| Feature | What it does | What the user can do | Phase |
|---|---|---|---|
| Composite Opportunity Score | Scores and ranks every potential export market 0–100 using a weighted index built around Afghan export conditions: market growth, tariff rates, price competitiveness, and market access etc. | A raisin producer selects dried fruits and instantly sees a ranked list of 20 markets: Germany at 82, India at 76, Indonesia at 61, with a clear breakdown of why each market scored that way. | 1 |
| Customs & Tariff Breakdown | Shows the complete customs cost picture for any product to any market: tariff, preferential rate under trade agreements, VAT on import, port fees, and anti-dumping duties. | An exporter of fresh grapes to Russia can see the 5% MFN tariff, 20% Russian VAT on import, $40/tonne port fees, and that the total customs burden adds 28% to the FOB price, helping them decide if the margin still works. | 1 |
| Top Importers Directory | Searchable directory of the world's largest importing companies and buying organisations for each product category, with purchasing volumes, import origins and preferred quality standards. | A dried fruit processor in Herat can search for the top 20 importers of dried apricots in Germany, see that three buyers account for 40% of German imports. | 1 |
| Excel & Data Export | Allows users to download datasets for any product, market or analysis as a formatted Excel workbook: price tables, tariff schedules, demand data by year, competitor breakdowns and HS code lists. | User selects ten products, and downloads a structured Excel workbook with one sheet per product showing five years of trade data, tariff rates and top competitors, saving days of manual data collection. | 1 |
| Regulatory & Compliance Hub (AI) | Single place to look up every regulatory requirement an Afghan exporter faces in any destination: tariffs, import bans, food safety standards, labelling rules, sanitary certificates, and sanctions status, explained in plain language. Plus regulatory change alerts. | An exporter sending dried figs to the EU can see the pesticide residue limits under EU regulation 396/2005, what certificate is required, that the tariff is 3.2%, and that there is no sanctions barrier, all in one screen. | 1 |
| HS Code Identifier (AI) | AI layer that lets users describe their product in plain Dari, Pashto or English and returns the correct HS code, related codes, and all trade data linked to it. | A carpet weaver types 'wool carpet' in Dari and gets HS 5701.10, the tariff rate in Germany, top competing exporters, and the rest of the tool pre-filled with that product's data. | 2 |
| Route & Logistics Planner | Shows open border crossings, available transport routes and basic logistics information for exporting from Afghanistan. | An exporter can check which borders are currently open, filter by route type, and see basic transit information to their target market. | 2 |
| Demand & Competition Analyzer | Shows how much of a product a target market is importing, how demand has grown over five years, which countries are supplying it and at what market share, and where Afghanistan stands relative to those competitors. Plus export country profiles. | An almond producer can see India imported $340m of almonds in 2024, demand grew 12% annually, the US holds 68% market share and Afghanistan holds 3%, showing a large untapped gap Afghan exporters could pursue if they match US quality grades. | 2 |
| Trade Facilitation Centre + Roadmap | Practical resources covering every step of the export process: customs agents, freight forwarders, export finance, trade insurance, Afghan government export programmes and international donor support. | A first-time exporter in Jalalabad who has found a buyer in India can find a licensed customs agent in Nangarhar, understand what export finance AISA or UN programmes offer, and find a freight forwarder for the Torkham–Wagah corridor. | 2 |
| Pricing & Profit Estimator | Shows indicative price ranges for Afghan export products in destination markets based on available trade data. | An exporter can look up what Afghan dried fruits are currently selling for in India or Germany, and compare that to prices from competing countries. | 3 |
| Industry & Sector Intelligence | Tracks structural changes in the industries Afghanistan exports to: consumer trends, technology shifts, regulatory tightening, major buyers entering or leaving. | A carpet exporter is alerted that hand-knotted carpet imports to Germany fell 8% in 2024, prompting them to consider the US market where hand-knotted demand is growing, or adding a modern design collection. | 3 |

### Methodology of the Opportunity Score

A composite **Opportunity Score** system has been developed to provide information to MSMEs wishing to identify and compare markets with trade potential. Under this system, a user can select a product (by HS code or name) and the tool provides access to a ranked list of markets, each rated with a composite Opportunity Score (0–100). Each market is scored across eight dimensions: market size, market growth, market quality, price competitiveness, tariff rate on Afghan goods, existing Afghan foothold, geographic proximity to Kabul, language/cultural similarity, FTA/preferential trade access. Each dimension is normalized to 0–100 before weighting. Scoring provides a relative opportunity comparison across the dimensions in question. The data sources used for the initial version are UN Comtrade, the World Bank Development Indicators and World Integrated Trade Solutions (WITS).

## Data Sources

| Data Source | Description | Features / Data | Has API |
|---|---|---|---|
| UN Comtrade | Provides detailed import and export statistics for goods and services reported by statistical authorities. | Trade indicators such as market growth and demand. Trade Balance view, bilateral data comparison. Mode of transport, 2nd partner country, customs procedure code, trade values in CIF and FOB. Useful for identifying markets, suppliers and competitors. | Yes |
| ITC Trade Map + ITC Export Potential Map | Provides indicators on export performance, international demand, alternative markets and competitive markets, as well as a directory of importing and exporting companies. | Yearly, quarterly and monthly trade data for 5,300 products at the 6-digit HS level and 10,000 products at National Tariff Line (NTL) level; information on importing, exporting and distributing enterprises in over 60 countries (company name, city, country, traded products, employees, turnover, contacts); pre-calculated trade indicators for the latest available year. | Yes (only in very specific circumstances) |
| World Bank WITS | Summary trade, tariff, non-tariff and development indicators. Databases derived from official data sources. Search across different preferential trade agreements. Tariff cut simulation tools. | Tariffs imposed by countries for merchandise trade; trade indicators such as Revealed Comparative Advantage (RCA), world growth, country growth; top export and import partners; top products exported by countries; development indicators such as GDP, GNI per capita, trade balance as % of GDP. | Yes |
| NSIA Afghanistan | Statistical data collected by the government agency in Afghanistan. | Trade balance, value of main commodity exports and imports, macro-level trade indicators. | No |
| ACCI Afghanistan | Trade data collected by the Afghanistan Chamber of Commerce & Investment. | Trade data broken down by industry and export destination. | No |
| Market Access Map | Access, compare, analyse and download customs tariffs, tariff-rate quotas, trade remedies and non-tariff measures applicable to a specific good in any market. | Customs tariff comparison, identification of prospective markets for export diversification, tariff information, trade agreements, trade statistics. | No |
| EU Access to Market | Comprehensive resource for information on exporting and importing goods, services, investment, and procurement. | Information on tariffs, taxes, product regulations, and requirements for all EU countries and over 140 international markets. EU trade agreements. | No |
| WTO Tariff and Trade Data | Official tariff and import data for more than 150 economies, including annual data from 1996 onwards. Aggregates applied tariffs and import data notified in the WTO's Integrated Data Base (IDB) and bound duties in the Consolidated Tariff Schedules (CTS) database. | Bilateral trade flows, tariff profiles and partner relationships. Time series tariff and trade indicators, monthly trade values and growth trends. | Yes |
| FAO (FAOSTAT) | Free access to food and agriculture data for over 245 countries and territories, covering all FAO regional groupings. | Country-level data on commodity prices for agricultural goods, imports and exports. Detailed trade matrix. | Yes |
| Trade Atlas | Company-level buyers and suppliers data. | Search by importer company, exporter company, product detail, brand name or country of origin within a selected time period. | Yes |
| Kompass | Extensive B2B database with tens of thousands of companies. Ideal for finding buyers. | Business solutions such as sales and marketing, digital marketing, consulting and services. | Yes |
| OEC (Observatory of Economic Complexity) | Detailed global trade data covering over 5,000 subnational regions, 5,000 products, and thousands of firms. Explore trade patterns, compare economic performance, generate reports with clear visualizations. | Tariff simulator, trend forecast, growth prediction, export potential. | Yes |
| World Bank Logistics Performance Index (LPI) | Interactive benchmarking tool to help countries identify challenges and opportunities in trade performance. Latest dataset covers 2023–2024. | LPI 2.0 measures speed and connectivity of international supply chains based on supply chain tracking data across logistics modes (aviation, maritime, postal), derived from actual movements of air cargo, containers, and parcels. | No |
| UN ESCAP APTIAD | Online database of trade agreements in the Asia-Pacific region. | All preferential agreements within the region, an agreement-country matrix, and an advanced search engine (by country, agreement name, status, scope, WTO notification status, keywords). | No |

## Governance

### Capacity Building & Handover to ACCI/Chambers

The Market Intelligence Tool will be developed in collaboration with relevant stakeholders, from the development process through to delivery. The ICPSD Crisis Resilience team will be responsible for the technical development and design of the tool, in line with ACCI's key inputs and the MSME needs it identifies. The tool, which translates the trade intelligence needs diagnosed in collaboration with ACCI into digital functionalities, will undergo a technical handover to authorized staff at the MSME Support Centre once it is ready for use.

**The technical handover** will begin with the provision of practical training to Trade Information Officers (TIOs), using samples of Afghan products, covering all key tool features. Subsequently, access rights, login details and documents will be formally transferred to enable the TIOs to carry out the entire workflow independently.

## Open Questions

- If we identify the need for primary data, can we collect data through ACCI?
- Is there technical capacity to sustain the platform with real-time or new data? How to transfer subscription-based API data?
- Which data of ACCI is currently available for our use?

## References

[^1]: [ITC — Afghanistan: Advancing Trade Phase II](https://www.intracen.org/our-work/projects/afghanistan-advancing-trade-phase-ii)
[^2]: ADB, 2026
[^3]: Afghanistan's exports declined sharply to USD 78 million in March 2026, down 37.1 percent month-on-month and 21.8 percent year-on-year, reflecting severe trade disruptions (The World Bank, March 2026)
[^4]: Export Opportunity Brief
[^5]: [UNDP Private Sector Mapping Afghanistan](https://www.undp.org/afghanistan/publications/private-sector-mapping-afghanistan-english-summaries-dari-and-pashto)
[^6]: ITC
[^7]: UNDP Business group consultations
[^8]: UNDP MSME research 2025
