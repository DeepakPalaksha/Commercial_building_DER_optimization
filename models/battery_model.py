"""
Battery state-of-charge (SoC) model.

Default sizing: 125 kW / 250 kWh (2-hour duration), matching the
Elexity CPS partnership spec described in CONTEXT.md.

Round-trip efficiency 92% is split symmetrically: charge efficiency
sqrt(eta_rt) on each direction so the product equals eta_rt.

See PLAN.md -- Core Models section for design rationale.
"""
import numpy as np


class BatteryModel:
    """
    Simple battery model enforcing SoC, power, and energy constraints.

    All power in kW, energy in kWh, timestep dt in hours.
    """

    def __init__(
        self,
        power_kw: float = 125.0,
        energy_kwh: float = 250.0,
        efficiency_rt: float = 0.92,
        soc_min: float = 0.10,
        soc_max: float = 0.95,
        initial_soc: float = 0.50,
    ):
        """
        Args:
            power_kw:       Max charge / discharge rate (kW).
            energy_kwh:     Usable capacity (kWh).
            efficiency_rt:  Round-trip efficiency [0, 1].
            soc_min:        Minimum allowed SoC fraction.
            soc_max:        Maximum allowed SoC fraction.
            initial_soc:    Starting SoC fraction.
        """
        if not (0.0 < soc_min < soc_max <= 1.0):
            raise ValueError(
                f"Invalid SoC bounds: soc_min={soc_min}, soc_max={soc_max}"
            )
        if not (0.5 <= efficiency_rt <= 1.0):
            raise ValueError(
                f"Round-trip efficiency should be in [0.5, 1.0], "
                f"got {efficiency_rt}"
            )

        self.power_kw = power_kw
        self.energy_kwh = energy_kwh
        self.efficiency_rt = efficiency_rt
        self.soc_min = soc_min
        self.soc_max = soc_max
        self.soc = float(initial_soc)

        # One-way (charge or discharge) efficiency
        self._eta_one_way = float(np.sqrt(efficiency_rt))

    # ── Read-only properties ──────────────────────────────────────────────

    @property
    def soc_kwh(self) -> float:
        """Current stored energy in kWh."""
        return self.soc * self.energy_kwh

    @property
    def available_discharge_kw(self) -> float:
        """Maximum power deliverable right now (limited by SoC floor)."""
        available_kwh = (self.soc - self.soc_min) * self.energy_kwh
        max_from_soc = available_kwh / 0.25 * self._eta_one_way
        return min(self.power_kw, max_from_soc)

    @property
    def available_charge_kw(self) -> float:
        """Maximum power absorbable right now (limited by SoC ceiling)."""
        headroom_kwh = (self.soc_max - self.soc) * self.energy_kwh
        max_from_soc = headroom_kwh / 0.25 / self._eta_one_way
        return min(self.power_kw, max_from_soc)

    # ── State transition methods ──────────────────────────────────────────

    def charge(self, power_kw: float, dt: float = 0.25) -> float:
        """
        Charge the battery.

        Args:
            power_kw: Requested charge power (kW). Clipped to limits.
            dt:       Timestep in hours.

        Returns:
            Actual grid power drawn (kW), accounting for charge efficiency.
        """
        power_kw = min(power_kw, self.power_kw)
        if power_kw <= 0:
            return 0.0

        # Energy entering the battery (after charge-side losses)
        energy_in = power_kw * dt * self._eta_one_way
        headroom = (self.soc_max - self.soc) * self.energy_kwh
        energy_in = min(energy_in, headroom)

        self.soc += energy_in / self.energy_kwh

        # Grid draw = energy_in / charge efficiency / dt
        grid_power = (energy_in / self._eta_one_way) / dt
        return round(grid_power, 3)

    def discharge(self, power_kw: float, dt: float = 0.25) -> float:
        """
        Discharge the battery.

        Args:
            power_kw: Requested discharge power (kW). Clipped to limits.
            dt:       Timestep in hours.

        Returns:
            Actual power delivered to building (kW), after efficiency loss.
        """
        power_kw = min(power_kw, self.power_kw)
        if power_kw <= 0:
            return 0.0

        # Energy leaving the battery (before discharge-side losses)
        energy_out_dc = power_kw * dt / self._eta_one_way
        available = (self.soc - self.soc_min) * self.energy_kwh
        energy_out_dc = min(energy_out_dc, available)

        self.soc -= energy_out_dc / self.energy_kwh

        # Power delivered = energy after discharge losses / dt
        delivered_power = (energy_out_dc * self._eta_one_way) / dt
        return round(delivered_power, 3)

    def reset(self, soc: float = 0.50) -> None:
        """Reset SoC to a given fraction (default 50%)."""
        if not (self.soc_min <= soc <= self.soc_max):
            raise ValueError(
                f"Reset SoC {soc} outside bounds "
                f"[{self.soc_min}, {self.soc_max}]"
            )
        self.soc = float(soc)

    def state_dict(self) -> dict:
        """Return a snapshot of current battery state."""
        return {
            "soc": round(self.soc, 4),
            "soc_kwh": round(self.soc_kwh, 2),
            "power_kw": self.power_kw,
            "energy_kwh": self.energy_kwh,
            "efficiency_rt": self.efficiency_rt,
        }

    def __repr__(self) -> str:
        return (
            f"BatteryModel("
            f"{self.power_kw}kW/{self.energy_kwh}kWh, "
            f"SoC={self.soc:.1%}, "
            f"eta_rt={self.efficiency_rt:.0%})"
        )


if __name__ == "__main__":
    bat = BatteryModel()
    print(f"Initial state: {bat}")

    # ── Test 1: basic charge/discharge sequence ──────────────────────
    print("\n-- Test 1: charge 4 hr at 60 kW then discharge 2 hr --")
    print(f"  Start SoC: {bat.soc:.1%}  ({bat.soc_kwh:.1f} kWh)")
    for _ in range(16):
        bat.charge(60.0, dt=0.25)
    print(f"  After 4hr charge:  {bat}")
    assert bat.soc_min <= bat.soc <= bat.soc_max, "SoC out of bounds (charge)!"

    for _ in range(8):
        bat.discharge(125.0, dt=0.25)
    print(f"  After 2hr discharge: {bat}")
    assert bat.soc_min <= bat.soc <= bat.soc_max, "SoC out of bounds (discharge)!"

    # ── Test 2: true round-trip efficiency (start from SoC_min) ──────
    print("\n-- Test 2: round-trip efficiency (empty -> full -> empty) --")
    bat.reset(soc=bat.soc_min)
    print(f"  Start: {bat}")

    total_grid_kwh = 0.0
    for _ in range(200):   # enough steps to fully charge
        grid_kw = bat.charge(125.0, dt=0.25)
        total_grid_kwh += grid_kw * 0.25
        if bat.soc >= bat.soc_max - 1e-6:
            break

    stored_kwh = (bat.soc_max - bat.soc_min) * bat.energy_kwh
    charge_eff = stored_kwh / total_grid_kwh
    print(
        f"  Charge: drew {total_grid_kwh:.1f} kWh, "
        f"stored {stored_kwh:.1f} kWh, "
        f"eta_charge={charge_eff:.3f} "
        f"(expect sqrt({bat.efficiency_rt})={bat._eta_one_way:.3f})"
    )

    total_delivered_kwh = 0.0
    for _ in range(200):   # enough steps to fully discharge
        delivered_kw = bat.discharge(125.0, dt=0.25)
        total_delivered_kwh += delivered_kw * 0.25
        if bat.soc <= bat.soc_min + 1e-6:
            break

    discharge_eff = total_delivered_kwh / stored_kwh
    rt_eff = total_delivered_kwh / total_grid_kwh
    print(
        f"  Discharge: {stored_kwh:.1f} kWh stored -> "
        f"{total_delivered_kwh:.1f} kWh delivered, "
        f"eta_discharge={discharge_eff:.3f}"
    )
    print(
        f"  Round-trip: {total_delivered_kwh:.1f} / "
        f"{total_grid_kwh:.1f} = {rt_eff:.3f} "
        f"(expected {bat.efficiency_rt:.2f})"
    )
    assert abs(rt_eff - bat.efficiency_rt) < 0.02, (
        f"RT efficiency {rt_eff:.3f} far from {bat.efficiency_rt}"
    )

    # ── Test 3: SoC clipping (overcharge attempt) ─────────────────────
    print("\n-- Test 3: overcharge guard (SoC near ceiling) --")
    bat.reset(soc=0.94)
    grid_kw = bat.charge(125.0, dt=0.25)
    print(
        f"  Requested 125 kW, drew {grid_kw:.1f} kW, "
        f"SoC={bat.soc:.4f} (max={bat.soc_max})"
    )
    assert bat.soc <= bat.soc_max + 1e-9, "SoC exceeded max!"

    print("\n[OK] All battery model checks passed")
