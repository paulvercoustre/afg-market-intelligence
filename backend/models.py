"""SQLAlchemy ORM models — mirror the Alembic migration schema."""

from sqlalchemy import ARRAY, TIMESTAMP, Boolean, Column, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    category = Column(Text, nullable=False)
    hs_codes = Column(ARRAY(Text), nullable=False)
    description = Column(Text)

    trade_flows = relationship("TradeFlow", back_populates="product", cascade="all, delete-orphan")
    competitor_flows = relationship("CompetitorFlow", back_populates="product", cascade="all, delete-orphan")
    indicators = relationship("Indicator", back_populates="product", cascade="all, delete-orphan")


class Market(Base):
    __tablename__ = "markets"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False, unique=True)
    country_name = Column(Text)
    region = Column(Text)


class MarketContext(Base):
    """World Bank development indicators per country per year."""
    __tablename__ = "market_context"

    id = Column(Integer, primary_key=True)
    country_code = Column(Text, nullable=False)
    year = Column(Integer, nullable=False)
    gdp_usd = Column(Numeric(20, 2))
    gdp_per_capita_usd = Column(Numeric(20, 2))
    lpi_score = Column(Numeric(5, 3))
    regulatory_quality = Column(Numeric(6, 4))
    political_stability = Column(Numeric(6, 4))
    fetched_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class TradeFlow(Base):
    __tablename__ = "trade_flows"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    importer_code = Column(Text, nullable=False)
    importer_name = Column(Text)
    year = Column(Integer, nullable=False)
    trade_value_usd = Column(Numeric(20, 2))
    trade_quantity = Column(Numeric(20, 4))
    quantity_unit = Column(Text)
    net_weight_kg = Column(Numeric(20, 4))
    fetched_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="trade_flows")


class CompetitorFlow(Base):
    __tablename__ = "competitor_flows"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    market_code = Column(Text, nullable=False)
    year = Column(Integer, nullable=False)
    supplier_code = Column(Text, nullable=False)
    supplier_name = Column(Text, nullable=False)
    trade_value_usd = Column(Numeric(20, 2))
    trade_quantity = Column(Numeric(20, 4))

    product = relationship("Product", back_populates="competitor_flows")


class Indicator(Base):
    __tablename__ = "indicators"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    market_code = Column(Text, nullable=False)
    computed_for_year = Column(Integer, nullable=False)

    # Trade indicators
    trade_data_year = Column(Integer)  # year the trade fields below actually came from -- can be earlier than computed_for_year if this market's Comtrade submission for that year hasn't landed yet
    global_market_size_usd = Column(Numeric(20, 2))
    afg_export_value_usd = Column(Numeric(20, 2))
    yoy_growth_pct = Column(Numeric(10, 4))
    cagr_pct = Column(Numeric(10, 4))
    absolute_growth_usd = Column(Numeric(20, 2))
    growth_pct = Column(Numeric(10, 4))
    first_year = Column(Integer)
    last_year = Column(Integer)
    market_share_pct = Column(Numeric(10, 6))
    afg_supplier_rank = Column(Integer)
    unit_price_usd = Column(Numeric(20, 6))
    market_avg_price_usd = Column(Numeric(20, 6))
    price_vs_market_pct = Column(Numeric(10, 4))
    price_competitiveness = Column(Text)

    # Opportunity score (composite 0–100)
    opportunity_score = Column(Numeric(5, 2))

    # Static context
    distance_km = Column(Integer)
    has_fta = Column(Boolean)
    language_similarity = Column(Numeric(4, 3))

    # World Bank context (denormalised for query efficiency)
    gdp_per_capita_usd = Column(Numeric(20, 2))
    lpi_score = Column(Numeric(5, 3))
    lpi_score_year = Column(Integer)  # year lpi_score was actually reported for -- LPI is triennial
    regulatory_quality = Column(Numeric(6, 4))
    regulatory_quality_year = Column(Integer)  # WGI lags 1-2 years behind computed_for_year
    political_stability = Column(Numeric(6, 4))
    political_stability_year = Column(Integer)

    # WITS tariff data
    tariff_rate_pct = Column(Numeric(6, 3))
    tariff_indicator = Column(Text)  # 'AHS' (preferential) or 'MFN' (general)
    tariff_year = Column(Integer)  # year the rate was actually reported for -- can be earlier than computed_for_year, WITS lags

    # Sub-scores (0–100 each)
    score_market_size = Column(Numeric(5, 2))
    score_market_growth = Column(Numeric(5, 2))
    score_market_quality = Column(Numeric(5, 2))
    score_price_competitiveness = Column(Numeric(5, 2))
    score_afg_foothold = Column(Numeric(5, 2))
    score_distance = Column(Numeric(5, 2))
    score_language = Column(Numeric(5, 2))
    score_fta = Column(Numeric(5, 2))
    score_tariff = Column(Numeric(5, 2))

    computed_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="indicators")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    run_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    status = Column(Text, nullable=False)
    products_updated = Column(Integer, default=0)
    errors_json = Column(JSONB)
