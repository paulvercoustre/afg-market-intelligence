"""Unit tests for rule-based next-steps generation in discovery service."""

from backend.services.discovery import _build_next_steps


def _base_row(**overrides) -> dict:
    row = {
        "has_fta": False,
        "distance_km": 5000,
        "price_competitiveness": "Average",
        "tariff_rate_pct": None,
        "tariff_indicator": None,
    }
    row.update(overrides)
    return row


class TestBuildNextSteps:
    def test_always_includes_documentation_and_buyers(self):
        steps = _build_next_steps(_base_row(), "356")
        titles = [s["title"] for s in steps]
        assert "Verify export documentation requirements" in titles
        assert "Identify and contact buyers" in titles
        assert "Attend relevant trade fairs" in titles

    def test_steps_are_sequentially_ordered(self):
        steps = _build_next_steps(_base_row(), "356")
        orders = [s["order"] for s in steps]
        assert orders == list(range(1, len(steps) + 1))

    def test_fta_branch_adds_preferential_tariff_step(self):
        steps = _build_next_steps(_base_row(has_fta=True), "356")
        titles = [s["title"] for s in steps]
        assert "Claim preferential tariff rates" in titles

    def test_no_fta_skips_preferential_step(self):
        steps = _build_next_steps(_base_row(has_fta=False), "356")
        titles = [s["title"] for s in steps]
        assert "Claim preferential tariff rates" not in titles

    def test_high_tariff_adds_planning_step(self):
        steps = _build_next_steps(
            _base_row(tariff_rate_pct=20.0, tariff_indicator="MFN"),
            "840",
        )
        titles = [s["title"] for s in steps]
        assert any("high import tariff" in t.lower() for t in titles)

    def test_low_tariff_adds_acceleration_step(self):
        steps = _build_next_steps(_base_row(tariff_rate_pct=2.0), "840")
        titles = [s["title"] for s in steps]
        assert any("low tariff barrier" in t.lower() for t in titles)

    def test_near_market_adds_overland_step(self):
        steps = _build_next_steps(_base_row(distance_km=2000), "586")
        titles = [s["title"] for s in steps]
        assert "Explore overland trade routes" in titles

    def test_distant_market_skips_overland_step(self):
        steps = _build_next_steps(_base_row(distance_km=8000), "840")
        titles = [s["title"] for s in steps]
        assert "Explore overland trade routes" not in titles

    def test_competitive_pricing_adds_outreach_step(self):
        steps = _build_next_steps(_base_row(price_competitiveness="Highly Competitive"), "356")
        titles = [s["title"] for s in steps]
        assert "Lead with price in buyer outreach" in titles

    def test_non_competitive_skips_outreach_step(self):
        steps = _build_next_steps(_base_row(price_competitiveness="Above Market"), "356")
        titles = [s["title"] for s in steps]
        assert "Lead with price in buyer outreach" not in titles

    def test_competitive_label_also_triggers_outreach(self):
        steps = _build_next_steps(_base_row(price_competitiveness="Competitive"), "356")
        titles = [s["title"] for s in steps]
        assert "Lead with price in buyer outreach" in titles
