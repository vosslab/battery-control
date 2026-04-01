# Battery control strategy

A "set it and forget it" flow chart that uses only two reliable inputs available every 3 minutes: ComEd price and local inverter solar power. Weather is optional and not required.

The design goal: fill the battery when solar is available, then spend it during expensive grid hours, while avoiding dumb cycling and avoiding running out too early in the evening.

## EP Cube mode semantics

Mode behavior, charging sources, and reserve semantics are documented in
[docs/EPCUBE_MODE_BEHAVIOR.md](docs/EPCUBE_MODE_BEHAVIOR.md). Key points for
strategy decisions:

- Self-consumption: PV-only charging, reserve is a discharge floor
- Backup: grid-charges to reach reserve, reserve is a target (not just a floor)
- This installation must not charge from grid (site constraint)

### Controller actuator capabilities

The controller cannot set a discharge rate. It can only:

- Choose the EP Cube mode (Self-consumption or Backup).
- Set the reserve SoC floor.

The inverter decides the actual discharge rate based on house load. The controller influences discharge indirectly by raising or lowering the SoC floor.

### API data fields

EP Cube reports these power readings via the `homeDeviceInfo` API endpoint (raw values multiplied by 10 to get watts):

| API field | Normalized key | Description |
| --- | --- | --- |
| `solarPower` | `solar_power_watts` | Current PV generation |
| `gridPower` | `grid_power_watts` | Grid import (positive) or export (negative) |
| `smartHomePower` | `smart_home_power_watts` | Total house load (best candidate for usage) |
| `backUpPower` | `backup_power_watts` | Load on the backup panel |
| `nonBackUpPower` | `non_backup_power_watts` | Load on the non-backup panel |
| `batteryPower` | `battery_power_watts` | Battery charge/discharge power (needs more data) |
| `batterySoc` | `battery_soc` | Battery state of charge (percent) |
| `workStatus` | `work_status` | Current EP Cube mode number |

## Controller policy actions

The controller uses three policy actions. Each determines intent, EP Cube mode, and SoC reserve rule:

| Policy action | Intent | EP Cube mode | WeMo | Reserve SoC rule |
| --- | --- | --- | --- | --- |
| `CHARGE_FROM_SOLAR` | Fill battery from PV | Self-consumption | both off | target SoC 100% (all seasons) |
| `DISCHARGE_ENABLED` | Battery serves load | Self-consumption | discharge on | floor from interpolated price anchors |
| `DISCHARGE_DISABLED` | Block discharge | Backup | both off | max(current SoC, configured hold floor) |

### Seasonal intent

Three seasons drive battery strategy, auto-detected by month:

- **Summer** (May-Sep): maximize stored energy for evening A/C. Charge to 100% from solar whenever practical.
- **Shoulder** (Mar-Apr, Oct-Nov): transitional months with mixed solar. Charge to 100%. Slightly more conservative discharge floors than summer.
- **Winter** (Dec-Feb): charge to 100% but expect many days with zero solar production (snow, short days). More conservative discharge floors since refill is unreliable.

The controller implements its own tariff logic using ComEd real-time pricing rather than the EP Cube's built-in TOU schedule.

### Price input: worst-case predictor

The price fed to the decision engine is not the instantaneous ComEd rate. It comes from `comedlib.getPredictedRate()`, which is intentionally a pessimistic (worst-case) estimator. It clamps negative and near-zero prices to 1.0 cent, floors the trend slope at +0.1 (never predicts a declining trend), computes three independent estimates (mean plus standard deviation, linear-regression slope extrapolation, and a weighted average of max/mean/recent), and returns the highest of the three. This conservative bias means the controller sees prices as higher than they may actually be, which prevents discharging the battery on a brief price dip that reverses shortly after.

### Price input: usage cutoff

The controller also fetches `comedlib.getReasonableCutOff()`, a time-aware cutoff price that determines whether energy should be conserved or consumed. The cutoff starts from the 75th percentile of 24-hour rates, adjusts for weekends (+0.9c), late night (+0.8c), and solar peak hours (Gaussian bonus up to +1.5c centered at noon), with a floor of 1.0c.

- If predicted rate > cutoff: **conserve** (prices are high, export surplus to grid)
- If predicted rate <= cutoff: **consume** (prices are low, charge battery from surplus)

This cutoff is the primary gate for discharge decisions in both daylight and night logic. Time-of-day effects come through the cutoff itself (which adjusts for solar peak hours, late night, and weekends), not through a separate peak-window state machine.

## Flow chart

### A. Guards (always run first)

1. If battery SoC <= Hard Reserve (example 20% winter, 15% shoulder, 10% summer)
Then: `DISCHARGE_DISABLED`. Stop.
2. If inverter solar power is unavailable (night or inverter off)
Then: go to Night logic (section D).
3. Otherwise solar is available
Then: go to Daylight logic (section B).

### B. Daylight logic (solar capture)

Goal: charge from solar. Avoid discharging unless prices are above cutoff or you need headroom to avoid wasting solar.

1. Compute "Solar Surplus" = solar generation minus house load.
If you cannot measure load, approximate surplus by battery charging rate or net export if available.
2. If Surplus > 0 (solar is excess)
  - 2x. If predicted price > usage cutoff (conserve mode): export surplus to grid instead of charging battery. Use price-to-SoC anchors for the discharge floor so the battery is ready to respond instantly if a load spike exceeds solar, without waiting up to 2 minutes for the next controller cycle. `DISCHARGE_ENABLED` with interpolated floor. Stop.
  - 2a. If SoC < 100%
Then: `CHARGE_FROM_SOLAR` to fill battery. Stop.
  - 2b. If SoC >= 100% (battery full)
Then: create headroom only if needed. If battery is near full and price is above cutoff, `DISCHARGE_ENABLED` with interpolated price floor. If battery is near full and price is negative, also `DISCHARGE_ENABLED` with headroom band to absorb solar instead of exporting at a loss. Otherwise `CHARGE_FROM_SOLAR`. Stop.
3. If Surplus <= 0 (solar not excess, likely clouds or high load)
  - 3a. If predicted price > usage cutoff: `DISCHARGE_ENABLED` with interpolated price floor. Stop.
  - 3b. Else: `DISCHARGE_DISABLED` to preserve SoC for evening. Stop.

### C. Night logic (no solar)

Goal: preserve battery unless prices justify discharge.

- If price > usage cutoff and SoC > Night Floor: `DISCHARGE_ENABLED` with interpolated price floor (clamped to at least Night Floor, example 35% winter, 30% shoulder, 25% summer).
- Otherwise: `DISCHARGE_DISABLED` with Night Floor.

### Price-floor interpolation

When price > cutoff and discharge is allowed, the SoC floor is computed by piecewise linear interpolation between season-adjusted anchor points. Prices below the first anchor clamp to its floor; prices above the last anchor clamp to its floor. Between anchors the floor changes smoothly.

Higher prices produce lower floors (more aggressive discharge). Lower prices produce higher floors (more conservative).

Summer anchors:

| Price (cents) | SoC floor |
| --- | --- |
| 8 | 50% |
| 10 | 30% |
| 20 | 20% |
| 30 | 10% |

Shoulder anchors (between summer and winter):

| Price (cents) | SoC floor |
| --- | --- |
| 8 | 55% |
| 10 | 38% |
| 20 | 25% |
| 30 | 15% |

Winter anchors (more conservative):

| Price (cents) | SoC floor |
| --- | --- |
| 8 | 60% |
| 10 | 45% |
| 20 | 30% |
| 30 | 20% |

Example: summer price 9c is midway between 8c and 10c, so floor = 40%.

### D. Command buffering

The command buffer prevents flapping by requiring the desired EP Cube state to be stable before sending hardware commands. Minimum SoC change threshold and optional periodic resend are configurable. See the command buffer module for details.

## Summary

The controller uses three policy actions (`CHARGE_FROM_SOLAR`, `DISCHARGE_ENABLED`, `DISCHARGE_DISABLED`) driven by predicted price vs cutoff, solar availability, and SoC. Each action maps to an EP Cube mode and a reserve SoC rule. The inverter handles actual power flow based on house load. Three seasons (summer, shoulder, winter) drive discharge floor behavior. All seasons charge to 100% from solar; seasons differ in discharge floors and reserves. Time-of-day effects come through the comedlib cutoff (which adjusts for solar peak hours, late night, and weekends), not through a separate peak-window routing state.
