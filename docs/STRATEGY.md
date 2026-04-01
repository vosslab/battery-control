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

- **Summer** (May-Sep): maximize stored energy for evening A/C and peak temperatures. Target 100% SoC before peak hours whenever practical.
- **Shoulder** (Mar-Apr, Oct-Nov): transitional months with mixed solar. Target 100% SoC. Slightly more conservative discharge floors than summer.
- **Winter** (Dec-Feb): target 100% SoC but expect many days with zero solar production (snow, short days). More conservative discharge floors since refill is unreliable.

The controller implements its own tariff logic using ComEd real-time pricing rather than the EP Cube's built-in TOU schedule.

### Price input: worst-case predictor

The price fed to the decision engine is not the instantaneous ComEd rate. It comes from `comedlib.getPredictedRate()`, which is intentionally a pessimistic (worst-case) estimator. It clamps negative and near-zero prices to 1.0 cent, floors the trend slope at +0.1 (never predicts a declining trend), computes three independent estimates (mean plus standard deviation, linear-regression slope extrapolation, and a weighted average of max/mean/recent), and returns the highest of the three. This conservative bias means the controller sees prices as higher than they may actually be, which prevents discharging the battery on a brief price dip that reverses shortly after.

## Flow chart

### A. Guards (always run first)

1. If battery SoC <= Hard Reserve (example 20% winter, 15% shoulder, 10% summer)
Then: `DISCHARGE_DISABLED`. Stop.
2. If inverter solar power is unavailable (night or inverter off)
Then: go to Night logic (section D).
3. Otherwise solar is available
Then: go to Daylight logic (section B).

### B. Daylight logic (solar capture)

Goal: charge from solar. Avoid discharging unless prices are extreme or you need headroom to avoid wasting solar.

1. Compute "Solar Surplus" = solar generation minus house load.
If you cannot measure load, approximate surplus by battery charging rate or net export if available.
2. If Surplus > 0 (solar is excess)
  - 2a. If SoC < Afternoon Target SoC (100% all seasons)
Then: `CHARGE_FROM_SOLAR` with target SoC as reserve. Stop.
  - 2b. If SoC >= Afternoon Target SoC
Then: create headroom only if needed. If battery is near full and price is extreme, `DISCHARGE_ENABLED` with headroom band (example 85 to 95%). If battery is near full and price is negative, also `DISCHARGE_ENABLED` with headroom band to absorb solar instead of exporting at a loss. Otherwise `CHARGE_FROM_SOLAR`. Stop.
3. If Surplus <= 0 (solar not excess, likely clouds or high load)
  - 3a. If current price is in an "Extreme" band (example >= 20 cents)
Then: `DISCHARGE_ENABLED` with Extreme Floor (example 10% summer, 15% shoulder, 20% winter). Stop.
  - 3b. Else: `DISCHARGE_DISABLED` to preserve SoC for evening. Stop.

### C. Transition trigger

If local time >= Peak Start (example 4:00pm) OR inverter solar power has been below a small threshold for 20 to 30 minutes (sun is going away)
Then: switch to Peak logic (section E).

### D. Night logic (no solar refill)

Goal: preserve battery unless prices are painful.

1. If time is inside Peak Window (example 4pm to 10pm)
Then: go to Peak logic (section E).
2. Else (late night, early morning)
  - If price >= Extreme band: `DISCHARGE_ENABLED` with extreme floor.
  - Otherwise: `DISCHARGE_DISABLED` with Night Floor (example 35% winter, 30% shoulder, 25% summer).

### E. Peak logic (evening arbitrage)

Goal: spend battery when prices are high, but preserve energy so you do not run out at 5pm.

1. Determine Season Mode
  - Summer mode: May to September, strong solar.
  - Shoulder mode: March to April and October to November, mixed solar.
  - Winter mode: December to February, weak or no solar.
2. Interpolate SoC floor from price anchors (season adjusted)

The floor is computed by piecewise linear interpolation between anchor points.
Prices below the first anchor clamp to its floor; prices above the last anchor
clamp to its floor. Between anchors the floor changes smoothly.

Summer anchors (peak window):

| Price (cents) | SoC floor |
| --- | --- |
| 8 | 50% |
| 10 | 30% |
| 20 | 20% |
| 30 | 10% |

Shoulder anchors (peak window, between summer and winter):

| Price (cents) | SoC floor |
| --- | --- |
| 8 | 55% |
| 10 | 38% |
| 20 | 25% |
| 30 | 15% |

Winter anchors (peak window, more conservative):

| Price (cents) | SoC floor |
| --- | --- |
| 8 | 60% |
| 10 | 45% |
| 20 | 30% |
| 30 | 20% |

Example: summer price 9c is midway between 8c and 10c, so floor = 40%.

3. Apply pacing heuristic (prevents early depletion)
Compute "Usable Energy" = battery energy above the selected floor.
Compute "Remaining Peak Hours" = hours until Peak End (example 10pm).
Use usable energy / remaining hours as a guideline for selecting a conservative SoC floor. The controller adjusts the floor, not the discharge rate.
  - If price is moderate: `DISCHARGE_ENABLED` with a higher floor to preserve energy for later.
  - If price is very high: `DISCHARGE_ENABLED` with the lowest seasonal floor.

4. Execute discharge decision
  - If SoC > Floor AND price is above discharge threshold: `DISCHARGE_ENABLED` with floor as reserve SoC.
  - Else: `DISCHARGE_DISABLED` to hold SoC.

### F. Reliability tricks for 3-minute scheduler

1. Hysteresis: require price to stay above a band boundary for 2 consecutive checks before switching bands. Same for dropping bands. This prevents flapping.
2. Minimum hold time: once you enter Peak logic, stay there until Peak End even if price dips briefly.
3. Token friction: do not send EP Cube mode commands unless the desired state has been stable for 2 to 3 cycles.

## Summary

The controller uses three policy actions (`CHARGE_FROM_SOLAR`, `DISCHARGE_ENABLED`, `DISCHARGE_DISABLED`) based on ComEd real-time pricing, solar power, and SoC. Each action maps to an EP Cube mode and a reserve SoC rule. The pacing heuristic guides floor selection, not discharge rate. The inverter handles actual power flow based on house load. Three seasons (summer, shoulder, winter) drive target SoC and discharge floor behavior. All seasons target 100% SoC when solar is available; seasons differ in discharge floors and reserves.
