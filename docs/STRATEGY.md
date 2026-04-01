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

- Choose the EP Cube mode (always Self-consumption under current strategy).
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

## Price-first policy

The primary decision axis is **price vs cutoff**, not solar/load flow direction. The controller sets a stable battery policy for each control interval. Solar and load determine physical outcomes under that policy, but do not change the policy itself.

### Strategy states

| State | Intent | EP Cube mode | WeMo | Reserve SoC rule |
| --- | --- | --- | --- | --- |
| `BELOW_CUTOFF` | Cheap grid, hold battery | Self-consumption | both off | 100% (battery does not discharge) |
| `ABOVE_CUTOFF` | Expensive grid, use battery | Self-consumption | discharge on | floor from interpolated price anchors |

### Why price-first

Solar and load can flip between control intervals (clouds, appliance cycles). A policy based on instantaneous flow direction produces fragile decisions. The price regime is stable over minutes to hours, so a price-first policy survives fluctuations. The EP Cube in self-consumption mode already handles solar/load transitions correctly once given a mode and reserve.

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

- If predicted rate > cutoff: **above cutoff** (prices are high, allow battery discharge)
- If predicted rate <= cutoff: **below cutoff** (prices are low, hold battery, charge from solar)

## Flow chart

### A. Guards (always run first)

1. If battery SoC <= Hard Reserve (example 20% winter, 15% shoulder, 10% summer)
Then: `BELOW_CUTOFF` with reserve at hard reserve. Stop.

### B. Cutoff deadband

A deadband stabilizes the decision boundary to prevent chattering near the cutoff.

- If price <= cutoff - buffer: `BELOW_CUTOFF`
- If price >= cutoff + buffer: `ABOVE_CUTOFF`
- If price is within the deadband: keep previous state

Default buffer is 0.5 cents. On startup (no previous state), raw comparison is used.

Example with cutoff 6.6c and buffer 0.5c:
- price <= 6.1c: BELOW_CUTOFF
- price >= 7.1c: ABOVE_CUTOFF
- 6.1c < price < 7.1c: keep current state

The command buffer separately protects the output from flapping; the deadband protects the decision boundary itself.

### C. Below cutoff (cheap grid)

Goal: do not spend battery. Grid is cheap.

- Self-consumption mode, reserve 100%
- Physical outcome: solar charges battery if surplus, grid covers any deficit, battery does not discharge
- Exception: negative price headroom. If SoC >= 95% and price is negative, set reserve to 85% to create room for solar absorption instead of exporting at a loss

### D. Above cutoff (expensive grid)

Goal: allow battery to serve load, reduce grid purchases.

- Self-consumption mode, reserve from price-SoC interpolation anchors
- If no solar available (night): clamp floor to at least night_floor_pct
- Physical outcome: battery discharges to cover load down to the price floor

### Price-floor interpolation

When above cutoff, the SoC floor is computed by piecewise linear interpolation between season-adjusted anchor points. Prices below the first anchor clamp to its floor; prices above the last anchor clamp to its floor. Between anchors the floor changes smoothly.

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

### E. Command buffering

The command buffer prevents flapping by requiring the desired EP Cube state to be stable before sending hardware commands. Minimum SoC change threshold and optional periodic resend are configurable. See the command buffer module for details.

## Summary

The controller uses two strategy states (`BELOW_CUTOFF`, `ABOVE_CUTOFF`) driven by predicted price vs cutoff. Both states use self-consumption mode; only the reserve SoC changes. Below cutoff: reserve 100% (hold battery). Above cutoff: reserve from price-SoC interpolation. The inverter handles actual power flow based on house load and solar availability. Three seasons (summer, shoulder, winter) drive discharge floor behavior. Time-of-day effects come through the comedlib cutoff (which adjusts for solar peak hours, late night, and weekends), not through separate day/night routing.
