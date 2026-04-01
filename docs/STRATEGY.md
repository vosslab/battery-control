# Battery control strategy

A "set it and forget it" flow chart that uses only two reliable inputs available every 3 minutes: ComEd price and local inverter solar power. Weather is optional and not required.

The design goal: fill the battery when solar is available, then spend it during expensive grid hours, while avoiding dumb cycling and avoiding running out too early in the evening.

## EP Cube hardware reference

EP Cube has three operation modes (from the official user manual):

### Self-consumption (API mode 1)

- PV power is used to supply load first, then charge the battery.
- Surplus solar charges the battery. Only once battery is fully charged is power exported to grid.
- When PV is less than load, battery discharges to support load until reserve SoC is reached.
- Below reserve SoC, grid supplies the load.
- PV power usage priority: Load > Battery > Grid.
- Load energy source priority: Photovoltaic > Battery > Grid.
- Battery charging source: **PV only** (battery does not charge from grid in this mode).

### Backup (API mode 3)

- Battery is charged to the user-set SoC for backup energy.
- Batteries charge from PV first; if PV is insufficient, grid power is used.
- When fully charged, the SoC difference above the reserve can still support load.
- On power failure or grid outage, EP Cube seamlessly switches to backup power.
- PV power usage priority: Load > Battery > Grid.
- Load energy source priority: Photovoltaic > Battery > Grid.
- Battery charging source: **PV > Grid** (battery can charge from grid in this mode).

### Time of Use (API mode 2)

- Owner defines up to 9 time slots: off-peak, peak, super peak, super off-peak.
- Off-peak and super off-peak: battery charges from grid at low price.
- Peak: behavior is consistent with Self-consumption mode.
- Super peak: battery discharges to support load down to 5% SoC.
- PV power usage priority: Load > Battery > Grid.
- Load energy source priority: Photovoltaic > Battery > Grid.
- Battery charging source: **PV only** (during peak/super peak).

### Constraint: no grid charging allowed

This installation is **not permitted to charge the battery from the grid**. This is a site constraint, not a hardware limitation. This means:

- Backup mode must be used carefully: it will attempt to charge from grid if PV is insufficient.
- Time of Use mode is not suitable: its off-peak behavior charges from grid by design.
- Self-consumption is the primary operating mode because it charges from PV only.
- The controller should only use Backup mode briefly to hold SoC (block discharge), not for sustained periods where grid charging could occur.

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

## EP Cube modes vs controller policy

The controller makes policy decisions and translates them into EP Cube hardware modes:

| Controller policy | EP Cube mode | Reserve SoC | Effect |
| --- | --- | --- | --- |
| Allow discharge | Self-consumption | Floor from price band | Battery serves house load above floor |
| Preserve energy | Backup | High floor (e.g. 80%) | Holds battery, but may grid-charge |
| Charge from solar | Self-consumption | Low floor | Solar charges battery, no grid discharge |

Because grid charging is not allowed at this site, Backup mode is used only for short-term discharge blocking. Extended use of Backup mode risks unwanted grid charging.

Time of Use mode is not used by the controller. The controller implements its own tariff logic using ComEd real-time pricing instead of the EP Cube's built-in TOU schedule.

## Flow chart

### A. Guards (always run first)

1. If battery SoC <= Hard Reserve (example 20% winter, 10% summer)
Then: set Backup mode to prevent discharge. Stop.
2. If inverter solar power is unavailable (night or inverter off)
Then: go to Night logic (section D).
3. Otherwise solar is available
Then: go to Daylight logic (section B).

### B. Daylight logic (solar capture)

Goal: charge from solar. Avoid discharging unless prices are extreme or you need headroom to avoid wasting solar.

1. Compute "Solar Surplus" = solar generation minus house load.
If you cannot measure load, approximate surplus by battery charging rate or net export if available.
2. If Surplus > 0 (solar is excess)
  - 2a. If SoC < Afternoon Target SoC (example 90% summer, 70% winter)
Then: set Self-consumption with high reserve. Let solar charge. Stop.
  - 2b. If SoC >= Afternoon Target SoC
Then: create headroom only if needed. If battery is near full and exporting or clipping solar, set Self-consumption with a headroom band (example 85 to 95%). If not exporting, hold. Stop.
3. If Surplus <= 0 (solar not excess, likely clouds or high load)
  - 3a. If current price is in an "Extreme" band (example >= 20 cents)
Then: set Self-consumption with Extreme Floor (example 10% summer, 20% winter). Stop.
  - 3b. Else: set Backup to preserve SoC for evening. Stop.

### C. Transition trigger

If local time >= Peak Start (example 4:00pm) OR inverter solar power has been below a small threshold for 20 to 30 minutes (sun is going away)
Then: switch to Peak logic (section E).

### D. Night logic (no solar refill)

Goal: preserve battery unless prices are painful.

1. If time is inside Peak Window (example 4pm to 10pm)
Then: go to Peak logic (section E).
2. Else (late night, early morning)
  - If price >= Extreme band: set Self-consumption with extreme floor.
  - Otherwise: set Backup with a conservative Night Floor (example 30 to 40% winter, 20 to 30% summer).

### E. Peak logic (evening arbitrage)

Goal: spend battery when prices are high, but preserve energy so you do not run out at 5pm.

1. Determine Season Mode
  - Summer mode: May to September or when daily solar is consistently strong.
  - Winter mode: October to April or when daily solar is inconsistent.
2. Select SoC Floor from price bands (season adjusted)

Example summer floors (peak window):
  - price < 8c: floor 50%
  - 8c to 10c: floor 30%
  - 10c to 20c: floor 20%
  - >= 20c: floor 10%

Example winter floors (peak window, more conservative):
  - price < 8c: floor 60%
  - 8c to 10c: floor 45%
  - 10c to 20c: floor 30%
  - >= 20c: floor 20% (optionally 15% if you accept more risk)

3. Apply pacing heuristic (prevents early depletion)
Compute "Usable Energy" = battery energy above the selected floor.
Compute "Remaining Peak Hours" = hours until Peak End (example 10pm).
Use usable energy / remaining hours as a guideline for selecting a conservative SoC floor. The controller adjusts the floor, not the discharge rate.
  - If price is moderate: set Self-consumption with a higher floor to preserve energy for later.
  - If price is very high: set Self-consumption with the lowest seasonal floor.

4. Execute discharge decision
  - If SoC > Floor AND price is above discharge threshold:
set Self-consumption with floor as reserve SoC.
  - Else: set Backup to hold SoC.

### F. Reliability tricks for 3-minute scheduler

1. Hysteresis: require price to stay above a band boundary for 2 consecutive checks before switching bands. Same for dropping bands. This prevents flapping.
2. Minimum hold time: once you enter Peak logic, stay there until Peak End even if price dips briefly.
3. Token friction: do not send EP Cube mode commands unless the desired state has been stable for 2 to 3 cycles.

## Summary

The controller uses ComEd real-time pricing and solar power to choose between Self-consumption (allow discharge with a floor) and Backup (hold SoC). The pacing heuristic selects the floor, not the discharge rate. The EP Cube inverter handles actual power flow based on house load. Grid charging is not permitted at this site, so Self-consumption is the primary mode and Backup is used only for short-term discharge blocking.
