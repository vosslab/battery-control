# EP Cube mode behavior

Observed and documented behavior of EP Cube operating modes relevant to battery
control strategy. This documents what each mode actually does on the hardware,
not what the strategy intends. See [docs/STRATEGY.md](docs/STRATEGY.md) for
decision logic.

Source: EP Cube 2.0 User Manual (Canadian Solar / EternalPlanet) and live
observations on this installation.

## Mode summary

| Mode | API value | PV charging | Grid charging | Discharges to load | Reserve meaning |
| --- | --- | --- | --- | --- | --- |
| Self-consumption | 1 | YES | NO | YES | Floor -- battery will not discharge below this SoC |
| Time of Use | 2 | YES | YES (off-peak) | YES (on-peak) | Schedule-dependent |
| Backup | 3 | YES | YES | NO (above reserve) | Target -- battery charges from any source to reach reserve |

## Self-consumption (mode 1)

Per the user manual:

- PV power supplies connected loads first, then surplus charges the battery
- Only once battery is fully charged is power exported to grid
- When PV is less than load, battery discharges to support load until reserve SoC
- Below reserve SoC, grid supplies the load
- PV power usage priority: Load > Battery > Grid
- Load energy source priority: Photovoltaic > Battery > Grid
- Battery charging source: **PV only**

Controller notes:

- Reserve (`selfConsumptioinReserveSoc`) acts as a discharge floor
- Setting reserve at current SoC effectively blocks discharge while still allowing
  solar charging when surplus appears
- API parameter: `selfConsumptioinReserveSoc` (note: typo is in the EP Cube API)

**Safe for:** holding battery at current SoC while capturing future solar surplus

## Backup (mode 3)

Per the user manual:

- Battery is charged to the user-set SoC for backup energy
- Batteries charge from PV first; if PV is insufficient, grid power is used
- Charging source priority: **PV > Grid**
- When fully charged, the SoC difference above the reserve can still support load
  (i.e., if reserve is not 100%, SoC above reserve is available for discharge)
- On power failure or grid outage, EP Cube seamlessly switches to backup power
- PV power usage priority: Load > Battery > Grid
- Load energy source priority: Photovoltaic > Battery > Grid

Controller notes:

- Reserve (`backupPowerReserveSoc`) is a **target**, not just a floor
- Setting reserve above current SoC **will cause grid charging**

**Observed 2026-04-01:** Backup mode with reserve 100% at SoC 62% caused ~6.3 kW
grid draw as the battery charged from grid to reach the 100% target.

**Safe for:** preventing discharge at low prices, but reserve must be at or below
current SoC to avoid grid charging

**Not safe for:** setting a high reserve to "prepare" for solar -- this grid-charges

## Time of Use (mode 2)

Per the user manual:

- Owner defines up to 9 time slots: off-peak, peak, super peak, super off-peak
- **Off-peak / super off-peak:** EP Cube charges battery from grid to 100% SoC;
  battery charging source: PV > Grid
- **Peak hours:** system operation is consistent with self-consumption mode;
  grid supplies load if SoC drops below reserve; battery charging source: PV > Grid
- **Super peak hours:** battery discharges to support load down to 5% SoC, even if
  SoC is below reserve; battery charging source: PV only
- Has `allowChargingXiaGrid` toggle in the iPhone app (not available in backup mode)

**`allowChargingXiaGrid`:** This is a TOU-mode-only toggle that controls whether
the battery charges from the grid during off-peak periods. Values: `"1"` = allow
grid charging, `"0"` = PV only. This toggle is **forbidden by the electricity
provider** for this installation. It does not control PV charging -- PV always
charges the battery in all modes regardless of this setting.

**Not suitable for this installation** because off-peak grid charging violates
site constraints (electricity provider prohibition, not just a preference).

## Key constraint

This installation must not charge the battery from the grid (PV-only charging).
This is a site-level policy, not a hardware limitation. The EP Cube supports grid
charging in both Backup and Time of Use modes.

## Strategy implications

| Scenario | Correct mode | Why |
| --- | --- | --- |
| Low price, want to hold SoC and capture solar | Self-consumption at current SoC | No grid charging, solar charges when surplus appears |
| Low price, want to block discharge only | Backup at current SoC | No grid charging if reserve = SoC, but no solar capture above SoC |
| High price, want to discharge | Self-consumption at low reserve | Allows discharge to cover load down to reserve floor |
| Extreme price, want max discharge | Self-consumption at hard reserve | Discharge as much as possible |

## Long-term storage

Per the user manual, if EP Cube will be unused for more than 30 days:

- Maintain ambient temperature 32-95 F (0-35 C)
- Leave last charge at 20-40% SoC and switch off Hybrid to avoid complete discharge
- Charge batteries once every 6 months to keep them healthy

## API fields reference

See [docs/EPCUBE_API_FIELDS.md](docs/EPCUBE_API_FIELDS.md) for full field
documentation.

Mode-specific payload fields for `/device/switchMode`:

- `workStatus`: mode number (1, 2, or 3)
- `selfConsumptioinReserveSoc`: reserve for mode 1 (string, 0-100)
- `backupPowerReserveSoc`: reserve for mode 3 (string, 0-100)
