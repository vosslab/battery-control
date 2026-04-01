# EP Cube API fields

Raw fields from the EP Cube `/device/homeDeviceInfo` endpoint, documented from
`--dump-raw` output on 2026-04-01.

## How to get a raw dump

Run the battery controller with `--dump-raw` to write the full raw API payload and
normalized state to JSON files in the current directory:

```bash
source source_me.sh && python3 -m battcontrol.battery_controller --dump-raw
```

This writes two files with alphabetically sorted keys:
- `epcube_raw_YYYYMMDD_HHMMSS.json` -- raw API payload (56 fields, sensitive fields masked)
- `epcube_normalized_YYYYMMDD_HHMMSS.json` -- normalized state (15 fields: power * 10, electricity in kWh)

The `run_daemon.py` wrapper strips `--dump-raw` after the first cycle so it only
fires once.

## Power fields (instantaneous)

Raw values are multiplied by 10 to get watts in the normalized output.

| Raw field | Normalized key | Unit | Description |
| --- | --- | --- | --- |
| `solarPower` | `solar_power_watts` | W (raw * 10) | Current PV generation |
| `gridPower` | `grid_power_watts` | W (raw * 10) | Grid import (positive) or export (negative) |
| `backUpPower` | `backup_power_watts` | W (raw * 10) | Load on backup panel |
| `smartHomePower` | `smart_home_power_watts` | W (raw * 10) | Total house load (= backUpPower + nonBackUpPower) |
| `nonBackUpPower` | `non_backup_power_watts` | W (raw * 10) | Load on non-backup panel |
| `batteryPower` | `battery_power_watts` | W (raw * 10) | Battery power (sign convention TBD, observed as 0 when idle) |
| `generatorPower` | not normalized | W (raw * 10) | Generator power (0 when no generator) |
| `evPower` | not normalized | W (raw * 10) | EV charger power (0 when no EV charger) |

## Energy fields (cumulative counters)

Confirmed daily counters in kWh by comparing 8:33 AM and 9:11 AM snapshots:
`gridElectricity` rose from 12.53 to 13.32 (+0.79 kWh in 38 min), consistent with
raw `gridPower` of ~108 (= 1080W). Exception: `batteryCurrentElectricity` appears
to be a lifetime counter, not daily (12.28 kWh at 9:11 AM with battery idle all morning).

| Raw field | Normalized key | Likely unit | Description |
| --- | --- | --- | --- |
| `gridElectricity` | `grid_electricity_kwh` | kWh | Cumulative grid energy (daily counter) |
| `solarElectricity` | `solar_electricity_kwh` | kWh | Cumulative solar energy |
| `solarDcElectricity` | not normalized | kWh | Solar DC component |
| `solarAcElectricity` | not normalized | kWh | Solar AC component |
| `backUpElectricity` | `backup_electricity_kwh` | kWh | Cumulative backup panel energy |
| `smartHomeElectricity` | `smart_home_electricity_kwh` | kWh | Cumulative total home energy |
| `nonBackUpElectricity` | `non_backup_electricity_kwh` | kWh | Cumulative non-backup panel energy |
| `generatorElectricity` | not normalized | kWh | Cumulative generator energy |
| `evElectricity` | not normalized | kWh | Cumulative EV charger energy |
| `batteryCurrentElectricity` | `battery_electricity_kwh` | kWh | Current stored energy in battery (see note below) |

### Counter verification results

Comparing 8:33 AM and 9:11 AM snapshots on 2026-04-01:

| Field | 8:33 AM | 9:11 AM | Delta | Rate check |
| --- | --- | --- | --- | --- |
| `gridElectricity` | 12.53 | 13.32 | +0.79 | ~1.25 kW avg matches raw ~1080-1120W |
| `solarElectricity` | 0.31 | 0.56 | +0.25 | ~0.39 kW avg matches raw 350-520W |
| `backUpElectricity` | 12.82 | 13.85 | +1.03 | ~1.63 kW avg matches raw 1480-1570W |
| `smartHomeElectricity` | 12.82 | 13.85 | +1.03 | Matches backUpElectricity exactly |
| `batteryCurrentElectricity` | 12.26 | 12.28 | +0.02 | Not a daily counter (see below) |

**Confirmed:** most electricity fields are daily counters in kWh that reset daily (reset
time TBD, likely midnight local).

### `batteryCurrentElectricity` interpretation

Not a daily or lifetime counter. Likely represents **current stored energy** in the
battery. At 9:19 AM the value was 12.28 kWh with SoC at 61%. Dividing gives an
implied total capacity of 12.28 / 0.61 = ~20.1 kWh, which is a plausible EP Cube
battery size. The +0.02 drift from 12.26 to 12.28 while `batteryPower` reported 0
is likely measurement noise or a tiny trickle below the power reporting threshold.

A third snapshot at 9:19 AM showed the value held steady at 12.28, consistent with
the battery remaining idle at 61% SoC.

### Remaining unknowns

- Daily counter reset time (midnight local or midnight UTC)
- Sign conventions for `batteryPower` (not yet observed non-zero)
- Confirm `batteryCurrentElectricity` = stored energy by observing a charge/discharge
  cycle (value should track SoC proportionally)

## Flow power fields

Confirmed duplicates of primary power fields (gridTotalPower=gridPower,
solarFlow=solarPower, backUpFlowPower=backUpPower). Not currently used.
Exception: `solarAcPower` differs slightly from `solarPower` (57 vs 52 at 9:11 AM),
possibly representing inverter output before efficiency losses.

| Raw field | Description |
| --- | --- |
| `solarFlow` | Solar flow power |
| `solarAcPower` | Solar AC power component |
| `solarDcPower` | Solar DC power component |
| `gridTotalPower` | Total grid power |
| `gridHalfPower` | Grid half power (unclear purpose) |
| `backUpFlowPower` | Backup load flow power |
| `nonBackUpFlowPower` | Non-backup load flow power |
| `generatorFlowPower` | Generator flow power |
| `evFlowPower` | EV charger flow power |

## Battery status

| Raw field | Normalized key | Description |
| --- | --- | --- |
| `batterySoc` | `battery_soc` | State of charge (percentage, 0-100) |
| `batteryCurrentElectricity` | `battery_electricity_kwh` | Current stored energy in battery |

## System status fields

| Raw field | Normalized key | Description |
| --- | --- | --- |
| `devId` | `device_id` | Device identifier (masked in logs) |
| `workStatus` | `work_status` | Current operating mode number |
| `status` | not normalized | System status string ("1" = normal) |
| `systemStatus` | not normalized | System status code (observed 4 and 6) |
| `isAlert` | not normalized | Alert flag ("0" = none) |
| `isFault` | not normalized | Fault flag ("0" = none) |
| `backUpType` | not normalized | Backup type (1 = standard) |
| `gridLight` | not normalized | Grid connection indicator ("1" = connected) |
| `generatorLight` | not normalized | Generator connection indicator ("3" = not connected) |
| `evLight` | not normalized | EV charger connection indicator ("0" = not connected) |
| `version` | not normalized | Firmware version string |
| `payloadVersion` | not normalized | API payload version (25) |

## Time fields

| Raw field | Description |
| --- | --- |
| `defCreateTime` | Timestamp in device default timezone |
| `defTimeZone` | Device default timezone (`America/Los_Angeles`) |
| `fromCreateTime` | Timestamp in user timezone |
| `fromTimeZone` | User timezone (`America/Chicago`) |
| `fromType` | Timezone type indicator ("1") |

## Capability flags

| Raw field | Description |
| --- | --- |
| `hasGenerator` | Generator connected (false) |
| `hasEv` | EV charger connected (false) |
| `newVersionTou` | New TOU schedule support (false) |
| `systemSpecialWorkMode` | Special work mode (0 = none) |
| `gridStandard` | Grid standard type (1) |
| `backupLoadsMode` | Backup loads mode (1) |
| `isNewDevice` | New device flag (true) |

## Other fields

| Raw field | Description |
| --- | --- |
| `selfHelpRate` | Daily self-sufficiency rate (percentage of load from solar, e.g. 4% at 9:11 AM) |
| `gridPowerFailureNum` | Count of grid power failures |
| `ressNumber` | Number of battery units (1) |
| `off_ON_Grid_Hint` | Human-readable status message |

## Example raw payload

From `--dump-raw` output at 2026-04-01 10:00 (sensitive fields masked, sorted
alphabetically). All 56 fields shown:

```json
{
  "backUpElectricity": 15.26,
  "backUpFlowPower": 59.0,
  "backUpPower": 59.0,
  "backUpType": 1,
  "backupLoadsMode": 1,
  "batteryCurrentElectricity": 12.8,
  "batteryPower": 0,
  "batterySoc": 64,
  "defCreateTime": "2026-04-01 08:00:19",
  "defTimeZone": "America/Los_Angeles",
  "devId": "***",
  "evElectricity": 0.0,
  "evFlowPower": 0.0,
  "evLight": "0",
  "evPower": 0.0,
  "fromCreateTime": "2026-04-01 10:00:19",
  "fromTimeZone": "America/Chicago",
  "fromType": "1",
  "generatorElectricity": 0.0,
  "generatorFlowPower": 0.0,
  "generatorLight": "3",
  "generatorPower": 0.0,
  "gridElectricity": 14.53,
  "gridHalfPower": 0.0,
  "gridLight": "1",
  "gridPower": 0.0,
  "gridPowerFailureNum": 0,
  "gridStandard": 1,
  "gridTotalPower": 0.0,
  "hasEv": false,
  "hasGenerator": false,
  "isAlert": "0",
  "isFault": "0",
  "isNewDevice": true,
  "newVersionTou": false,
  "nonBackUpElectricity": 0.0,
  "nonBackUpFlowPower": 0.0,
  "nonBackUpPower": 0.0,
  "off_ON_Grid_Hint": "EP CUBE is optimizing your energy independence for cost saving.",
  "payloadVersion": 25,
  "ressNumber": 1,
  "selfHelpRate": 5.0,
  "smartHomeElectricity": 15.26,
  "smartHomePower": 59.0,
  "solarAcElectricity": 1.1,
  "solarAcPower": 74.0,
  "solarDcElectricity": 0.0,
  "solarDcPower": 0.0,
  "solarElectricity": 1.1,
  "solarFlow": 67.0,
  "solarPower": 67.0,
  "status": "1",
  "systemSpecialWorkMode": 0,
  "systemStatus": 6,
  "version": "03030328025920251022",
  "workStatus": "1"
}
```

Normalized output (power * 10, electricity in kWh):

```json
{
  "backup_electricity_kwh": 15.26,
  "backup_power_watts": 590.0,
  "battery_electricity_kwh": 12.8,
  "battery_power_watts": 0.0,
  "battery_soc": 64,
  "device_id": "***",
  "grid_electricity_kwh": 14.53,
  "grid_power_watts": 0.0,
  "non_backup_electricity_kwh": 0.0,
  "non_backup_power_watts": 0.0,
  "smart_home_electricity_kwh": 15.26,
  "smart_home_power_watts": 590.0,
  "solar_electricity_kwh": 1.1,
  "solar_power_watts": 670.0,
  "work_status": "1"
}
```
