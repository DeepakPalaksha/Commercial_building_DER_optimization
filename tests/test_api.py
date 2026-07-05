"""
Smoke tests for the FastAPI service.
Run with: uv run pytest tests/test_api.py -v
No Docker needed -- uses in-process TestClient.
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    """Start test client with lifespan (loads meter + tariff data)."""
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["data_rows"] == 35040
    assert 150 <= data["peak_demand_kw"] <= 220


def test_tariff_has_summer_rates(client):
    r = client.get("/tariff")
    assert r.status_code == 200
    tariff = r.json()
    summer = tariff["energy_charges_per_kwh"]["summer"]
    assert abs(summer["on_peak"]["rate"] - 0.28317) < 0.001


def test_bill_monthly_july(client):
    r = client.post("/bill/monthly", json={"month": 7})
    assert r.status_code == 200
    data = r.json()
    assert data["month"] == 7
    assert data["total"] > 3000
    assert data["peak_demand_kw"] > 0


def test_bill_monthly_invalid(client):
    r = client.post("/bill/monthly", json={"month": 13})
    assert r.status_code == 422  # Pydantic validation


def test_bill_annual_twelve_months(client):
    r = client.post("/bill/annual", json={})
    assert r.status_code == 200
    data = r.json()
    assert len(data["months"]) == 12
    assert data["annual"]["annual_total"] > 50000


def test_cost_driver_shares_sum_to_100(client):
    r = client.post("/cost-driver", json={})
    assert r.status_code == 200
    shares = r.json()["shares"]
    total = (
        shares["energy_pct"] + shares["demand_pct"] + shares["fixed_pct"]
    )
    assert abs(total - 100.0) < 0.5


def test_optimize_returns_501_before_phase4(client):
    r = client.post(
        "/optimize",
        json={
            "month": 7,
            "solar_kw": 100,
            "battery_power_kw": 125,
            "battery_energy_kwh": 250,
            "enable_precool": True,
            "enable_dsgs": True,
        },
    )
    assert r.status_code == 501


def test_savings_annual_returns_waterfall(client):
    r = client.post(
        "/savings/annual",
        json={
            "solar_kw": 100,
            "battery_power_kw": 125,
            "battery_energy_kwh": 250,
            "enable_precool": True,
            "enable_dsgs": True,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["baseline_annual_bill"] > 50000
    assert data["total_savings"] > 0
    assert len(data["waterfall"]) >= 4
