"""
FastAPI service for Elexity building energy analysis.

Endpoints:
  GET  /health             -- data load check
  GET  /tariff             -- full SCE TOU-GS-3 rate schedule
  POST /bill/monthly       -- reconstruct one month's bill
  POST /bill/annual        -- reconstruct all 12 months
  POST /cost-driver        -- bill component % shares
  POST /optimize           -- run MILP optimizer for one month (Phase 4)
  POST /savings/annual     -- full-year savings waterfall + NPV

Swagger UI: http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc
"""
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException

from analysis.bill_calculator import (
    _load_meter,
    calculate_annual_bill,
    calculate_monthly_bill,
)
from analysis.tariff import load_tariff
from api.schemas import (
    AnnualSavingsRequest,
    HealthResponse,
    MonthlyBillResponse,
    MonthRequest,
    OptimizeRequest,
)

# ── Shared state loaded once at startup ──────────────────────────────────────
_df: pd.DataFrame = None
_tariff: dict = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _df, _tariff
    _df = _load_meter()
    _tariff = load_tariff()
    yield


app = FastAPI(
    title="Elexity Building Energy Analysis API",
    description=(
        "REST API for SCE TOU-GS-3 bill reconstruction, DER dispatch "
        "optimization, and savings analysis for a C&I secondary school "
        "in Southern California.\n\n"
        "**Data:** Calendar year 2023, 15-min interval, 35,040 rows\n\n"
        "**Tariff:** SCE TOU-GS-3 — summer on-peak demand $19.10/kW"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    """Confirm the service is running and data is loaded."""
    if _df is None:
        raise HTTPException(status_code=503, detail="Data not loaded")
    return HealthResponse(
        status="ok",
        data_rows=len(_df),
        peak_demand_kw=round(float(_df["demand_kw"].max()), 1),
    )


# ── Tariff ────────────────────────────────────────────────────────────────────
@app.get("/tariff", tags=["Tariff"])
def get_tariff():
    """Return the full SCE TOU-GS-3 rate schedule as JSON."""
    if _tariff is None:
        raise HTTPException(status_code=503, detail="Tariff not loaded")
    return _tariff


# ── Bill ──────────────────────────────────────────────────────────────────────
@app.post(
    "/bill/monthly",
    response_model=MonthlyBillResponse,
    tags=["Bill"],
)
def bill_monthly(req: MonthRequest):
    """Reconstruct one month's SCE TOU-GS-3 bill from meter data."""
    try:
        result = calculate_monthly_bill(_df, req.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/bill/annual", tags=["Bill"])
def bill_annual():
    """
    Reconstruct all 12 months' bills.

    Returns list of monthly rows plus annual totals dict.
    """
    annual = calculate_annual_bill(_df)
    rows = annual.to_dict(orient="records")
    totals = {
        "annual_total": round(float(annual["total"].sum()), 2),
        "annual_energy_charge": round(
            float(annual["energy_charge"].sum()), 2
        ),
        "annual_demand_charge": round(
            float(annual["demand_charge"].sum()), 2
        ),
        "annual_fixed_charge": round(
            float(annual["fixed_charge"].sum()), 2
        ),
        "annual_kwh": round(float(annual["total_kwh"].sum()), 1),
    }
    return {"months": rows, "annual": totals}


# ── Cost driver ───────────────────────────────────────────────────────────────
@app.post("/cost-driver", tags=["Analysis"])
def cost_driver():
    """
    Decompose annual bill into energy / demand / fixed % shares.

    Also returns monthly peak demand array for heatmap rendering.
    """
    annual = calculate_annual_bill(_df)
    grand = float(annual["total"].sum())
    shares = {
        "energy_pct": round(
            float(annual["energy_charge"].sum()) / grand * 100, 1
        ),
        "demand_pct": round(
            float(annual["demand_charge"].sum()) / grand * 100, 1
        ),
        "fixed_pct": round(
            float(annual["fixed_charge"].sum()) / grand * 100, 1
        ),
    }
    monthly_peaks = annual[["month", "peak_demand_kw"]].to_dict(
        orient="records"
    )
    return {"shares": shares, "monthly_peaks": monthly_peaks}


# ── Optimizer ─────────────────────────────────────────────────────────────────
@app.post("/optimize", tags=["Optimization"])
def optimize(req: OptimizeRequest):
    """
    Run MILP optimizer for one month with the specified DER configuration.

    Returns dispatch schedule and savings vs baseline bill.
    Currently returns 501 — full wire-up in Phase 4 / TASKS.md.
    """
    try:
        from models.optimizer import optimize_dispatch  # noqa: F401
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail=(
                "Optimizer not yet built (Phase 4). "
                "Complete TASKS.md Phase 4 first."
            ),
        )
    raise HTTPException(
        status_code=501, detail="Full wire-up pending Phase 4 tasks"
    )


# ── Savings ───────────────────────────────────────────────────────────────────
@app.post("/savings/annual", tags=["Optimization"])
def savings_annual(req: AnnualSavingsRequest):
    """
    Run all DER scenarios across the full year and return savings waterfall.

    Returns baseline bill, per-scenario bills, savings vs baseline,
    capital cost, simple payback, NPV (8%, 20 yr), and IRR.
    """
    from analysis.savings_calculator import (
        CAPEX,
        DSGS_ANNUAL_REVENUE,
        build_waterfall,
        calculate_payback,
        run_baseline,
        run_solar_hvac,
        run_solar_hvac_battery,
        run_solar_only,
    )

    baseline_bills = run_baseline(_df)
    solar_bills = run_solar_only(_df, solar_kw=req.solar_kw)
    solar_hvac_bills = run_solar_hvac(_df, solar_kw=req.solar_kw)
    solar_hvac_bat_bills = run_solar_hvac_battery(_df, solar_kw=req.solar_kw)

    b = float(baseline_bills["total"].sum())
    s = float(solar_bills["total"].sum())
    sh = float(solar_hvac_bills["total"].sum())
    shb = float(solar_hvac_bat_bills["total"].sum())
    dsgs_revenue = DSGS_ANNUAL_REVENUE if req.enable_dsgs else 0.0

    waterfall = build_waterfall(b, s, sh, shb, shb - dsgs_revenue)
    pb_full = calculate_payback(b - shb + dsgs_revenue, CAPEX["full_stack"])

    return {
        "baseline_annual_bill": round(b, 2),
        "solar_only_bill": round(s, 2),
        "solar_hvac_bill": round(sh, 2),
        "solar_hvac_battery_bill": round(shb, 2),
        "dsgs_annual_revenue": round(dsgs_revenue, 2),
        "total_savings": round(b - shb + dsgs_revenue, 2),
        "total_savings_pct": round((b - shb + dsgs_revenue) / b * 100, 1),
        "capex": CAPEX["full_stack"],
        "simple_payback_years": pb_full["simple_payback_years"],
        "npv": pb_full["npv"],
        "irr_approx": pb_full["irr_approx"],
        "waterfall": waterfall,
    }
