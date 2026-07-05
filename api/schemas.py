"""
Pydantic request and response models for the FastAPI service.
All monetary values in USD, power in kW, energy in kWh.
"""
from pydantic import BaseModel, Field


class MonthRequest(BaseModel):
    month: int = Field(..., ge=1, le=12, description="Month number 1-12")


class OptimizeRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    solar_kw: float = Field(
        100.0, ge=0, le=1000, description="Installed PV size (kW)"
    )
    battery_power_kw: float = Field(
        125.0, ge=0, le=500, description="Battery power rating (kW)"
    )
    battery_energy_kwh: float = Field(
        250.0, ge=0, le=2000, description="Battery capacity (kWh)"
    )
    enable_precool: bool = Field(
        True, description="Allow HVAC pre-cooling"
    )
    enable_dsgs: bool = Field(
        True, description="Enroll in DSGS demand response"
    )


class AnnualSavingsRequest(BaseModel):
    solar_kw: float = Field(100.0, ge=0, le=1000)
    battery_power_kw: float = Field(125.0, ge=0, le=500)
    battery_energy_kwh: float = Field(250.0, ge=0, le=2000)
    enable_precool: bool = True
    enable_dsgs: bool = True


class MonthlyBillResponse(BaseModel):
    month: int
    energy_charge: float
    demand_charge: float
    fixed_charge: float
    total: float
    peak_demand_kw: float
    on_peak_demand_kw: float
    total_kwh: float


class HealthResponse(BaseModel):
    status: str
    data_rows: int
    peak_demand_kw: float
