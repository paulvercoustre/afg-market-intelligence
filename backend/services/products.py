"""Service layer — queries the DB and assembles API response objects."""


from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from backend import schemas
from backend.country_names import resolve_country_name
from backend.models import CompetitorFlow, Indicator, Market, PipelineRun, Product, TradeFlow


def _find_product_by_hs(db: Session, hs_code: str) -> Product | None:
    """Locate a product by HS code, compatible with PostgreSQL ARRAY and SQLite TEXT."""
    clean = hs_code.replace(".", "").strip()
    # cast(ARRAY, String) → '{code1,code2}' in PG, plain text in SQLite — LIKE works on both
    return (
        db.query(Product)
        .filter(cast(Product.hs_codes, String).contains(clean))
        .first()
    )


def list_products(db: Session) -> list[schemas.ProductSummary]:
    products = db.query(Product).order_by(Product.category, Product.name).all()
    results = []
    for p in products:
        latest_indicator = (
            db.query(Indicator)
            .filter(Indicator.product_id == p.id)
            .order_by(Indicator.computed_for_year.desc())
            .first()
        )
        total_export = None
        last_year = None
        top_market_name = None
        has_data = False

        if latest_indicator:
            has_data = True
            last_year = latest_indicator.computed_for_year
            # Sum export value across all markets for the latest year
            agg = (
                db.query(func.sum(Indicator.afg_export_value_usd))
                .filter(
                    Indicator.product_id == p.id,
                    Indicator.computed_for_year == last_year,
                )
                .scalar()
            )
            total_export = float(agg) if agg else None
            # Top market by export value
            top = (
                db.query(Indicator)
                .filter(
                    Indicator.product_id == p.id,
                    Indicator.computed_for_year == last_year,
                )
                .order_by(Indicator.afg_export_value_usd.desc().nullslast())
                .first()
            )
            if top:
                market = db.query(Market).filter(Market.country_code == top.market_code).first()
                top_market_name = resolve_country_name(
                    top.market_code,
                    market.country_name if market else None,
                )

        results.append(schemas.ProductSummary(
            id=p.id,
            name=p.name,
            category=p.category,
            hs_codes=p.hs_codes,
            description=p.description,
            has_data=has_data,
            last_year=last_year,
            total_export_value_usd=total_export,
            top_market_name=top_market_name,
        ))
    return results


def get_product(db: Session, hs_code: str) -> schemas.ProductDetail | None:
    product = (
        db.query(Product)
        .filter(cast(Product.hs_codes, String).contains(hs_code.replace(".", "").strip()))
        .first()
    )
    if not product:
        return None

    latest_year = (
        db.query(func.max(Indicator.computed_for_year))
        .filter(Indicator.product_id == product.id)
        .scalar()
    )
    if not latest_year:
        return schemas.ProductDetail(
            id=product.id, name=product.name, category=product.category,
            hs_codes=product.hs_codes, description=product.description, markets=[],
        )

    indicators = (
        db.query(Indicator)
        .filter(Indicator.product_id == product.id, Indicator.computed_for_year == latest_year)
        .order_by(Indicator.afg_export_value_usd.desc().nullslast())
        .all()
    )

    markets = []
    for ind in indicators:
        market = db.query(Market).filter(Market.country_code == ind.market_code).first()
        markets.append(_indicator_to_schema(ind, market))

    return schemas.ProductDetail(
        id=product.id, name=product.name, category=product.category,
        hs_codes=product.hs_codes, description=product.description,
        markets=markets,
    )


def get_markets(db: Session, hs_code: str) -> list[schemas.MarketIndicator]:
    detail = get_product(db, hs_code)
    return detail.markets if detail else []


def get_market_detail(db: Session, hs_code: str, market_code: str) -> schemas.MarketDetail | None:
    product = (
        db.query(Product)
        .filter(cast(Product.hs_codes, String).contains(hs_code.replace(".", "").strip()))
        .first()
    )
    if not product:
        return None

    market = db.query(Market).filter(Market.country_code == market_code).first()
    market_name = resolve_country_name(market_code, market.country_name if market else None)

    latest_year = (
        db.query(func.max(Indicator.computed_for_year))
        .filter(Indicator.product_id == product.id)
        .scalar()
    )
    indicator_row = None
    if latest_year:
        ind = (
            db.query(Indicator)
            .filter(
                Indicator.product_id == product.id,
                Indicator.market_code == market_code,
                Indicator.computed_for_year == latest_year,
            )
            .first()
        )
        if ind:
            indicator_row = _indicator_to_schema(ind, market)

    # Competitor data for latest year
    competitors_raw = (
        db.query(CompetitorFlow)
        .filter(
            CompetitorFlow.product_id == product.id,
            CompetitorFlow.market_code == market_code,
            CompetitorFlow.year == (latest_year or 0),
        )
        .order_by(CompetitorFlow.trade_value_usd.desc())
        .limit(10)
        .all()
    )
    total_comp = sum((float(c.trade_value_usd or 0)) for c in competitors_raw)
    competitors = [
        schemas.CompetitorRow(
            supplier_code=c.supplier_code,
            supplier_name=resolve_country_name(c.supplier_code, c.supplier_name),
            trade_value_usd=float(c.trade_value_usd) if c.trade_value_usd else None,
            trade_quantity=float(c.trade_quantity) if c.trade_quantity else None,
            market_share_pct=(
                float(c.trade_value_usd) / total_comp * 100
                if c.trade_value_usd and total_comp > 0 else None
            ),
        )
        for c in competitors_raw
    ]

    # Trade history (Afghanistan to this market)
    history_raw = (
        db.query(TradeFlow)
        .filter(
            TradeFlow.product_id == product.id,
            TradeFlow.importer_code == market_code,
        )
        .order_by(TradeFlow.year)
        .all()
    )
    history = [
        schemas.TradeHistoryPoint(
            year=r.year,
            trade_value_usd=float(r.trade_value_usd) if r.trade_value_usd else None,
            trade_quantity=float(r.trade_quantity) if r.trade_quantity else None,
        )
        for r in history_raw
    ]

    return schemas.MarketDetail(
        market_code=market_code,
        market_name=market_name,
        product_id=product.id,
        product_name=product.name,
        indicator=indicator_row,
        competitors=competitors,
        trade_history=history,
    )


def get_pipeline_runs(db: Session, limit: int = 10) -> list[schemas.PipelineRunSummary]:
    runs = db.query(PipelineRun).order_by(PipelineRun.run_at.desc()).limit(limit).all()
    return [
        schemas.PipelineRunSummary(
            id=r.id,
            run_at=r.run_at.isoformat() if r.run_at else "",
            status=r.status,
            products_updated=r.products_updated or 0,
        )
        for r in runs
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _indicator_to_schema(ind: Indicator, market: Market | None) -> schemas.MarketIndicator:
    return schemas.MarketIndicator(
        market_code=ind.market_code,
        market_name=resolve_country_name(ind.market_code, market.country_name if market else None),
        afg_export_value_usd=_f(ind.afg_export_value_usd),
        global_market_size_usd=_f(ind.global_market_size_usd),
        market_share_pct=_f(ind.market_share_pct),
        afg_supplier_rank=ind.afg_supplier_rank,
        trade_data_year=ind.trade_data_year,
        afg_last_export_year=ind.afg_last_export_year,
        afg_last_export_value_usd=_f(ind.afg_last_export_value_usd),
        growth=schemas.GrowthMetrics(
            yoy_growth_pct=_f(ind.yoy_growth_pct),
            cagr_pct=_f(ind.cagr_pct),
            absolute_growth_usd=_f(ind.absolute_growth_usd),
            growth_pct=_f(ind.growth_pct),
            first_year=ind.first_year,
            last_year=ind.last_year,
        ),
        price=schemas.PriceMetrics(
            unit_price_usd=_f(ind.unit_price_usd),
            price_basis=ind.price_basis,
            market_avg_price_usd=_f(ind.market_avg_price_usd),
            price_vs_market_pct=_f(ind.price_vs_market_pct),
            price_competitiveness=ind.price_competitiveness,
        ),
    )


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
