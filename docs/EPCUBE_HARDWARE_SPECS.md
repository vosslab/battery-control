# EP Cube hardware specs

Extracted from EP Cube Datasheet NA English V2.8 (March 2025).
Model confirmed from installation invoice: Hybrid NA720G.
Battery activated November 17, 2025.

See also [docs/EPCUBE_MODE_BEHAVIOR.md](EPCUBE_MODE_BEHAVIOR.md) for mode semantics
and [docs/EPCUBE_API_FIELDS.md](EPCUBE_API_FIELDS.md) for API field documentation.

## This installation

| Parameter | Value | Source |
| --- | --- | --- |
| Model | EP Cube v1, Hybrid NA720G | Invoice |
| Total energy | 19.9 kWh (app reports 19.98) | Datasheet, EP Cube app |
| Battery modules | 6 | Datasheet (6 x 3.32 kWh) |
| Battery chemistry | Lithium iron phosphate (LFP) | Datasheet |
| Solar inverter max | ~6 kW | Installation |
| Grid voltage | 240V AC split phase | Datasheet |
| Smart Gateway | 1 | Invoice |
| Activated | 2025-11-27 | `/device/userDeviceInfo` |
| Warranty expires | 2035-11-27 | `/device/userDeviceInfo` |
| Location | Illinois, United States | `/device/userDeviceInfo` |

## Inverter specs (NA720G, 240V)

| Parameter | Value |
| --- | --- |
| Max AC output on-grid | 7.6 kW |
| Max inverter CEC efficiency | 93.93% |
| MPPTs | 4 |
| PV max input voltage | 600V |
| PV MPPT voltage range | 90-550V |
| Input current | 16A / 20A per MPPT |

## Battery charge and discharge limits

All values for the NA720G (19.9 kWh, 6 modules) at 240V.

| Parameter | Value |
| --- | --- |
| Max charge power (battery only, continuous) | 7.6 kW / 31.6A |
| Max discharge power (battery only, continuous) | 7.6 kW / 31.6A |
| AC output, PV + battery (full sun, continuous) | 7.6 kW / 31.6A |
| AC output, battery only (no sun, 10s burst) | 11.4 kVA |

### Practical limits in this installation

- **Charge** is bounded by excess solar after load: `charge = solar - load`.
  With a ~6 kW solar inverter and typical daytime load of 1-2 kW, max
  observed charge is ~2.2 kWh/hr. The 7.6 kW inverter limit never binds.
- **Discharge** is bounded by house load minus solar: `discharge = load - solar`.
  Max observed discharge is ~1.6 kWh/hr. The 7.6 kW inverter limit
  never binds at current load levels.

## General parameters

| Parameter | Value |
| --- | --- |
| Enclosure | NEMA 4X |
| Operating noise at 1m | < 50 dB |
| Charge temperature | 14-122 F / -10-50 C |
| Discharge temperature | -4-122 F / -20-50 C |
| Recommended operating temp | 32-86 F / 0-30 C |
| Max elevation | 9843 ft / 3000 m |
| Dimensions | 23.62 x 73.43 x 9.25 in / 600 x 1865 x 235 mm |
| System weight | 485 lbs / 220 kg |
| Battery module weight | 70 lbs / 32 kg each |
| Inverter weight | 77 lbs / 35 kg |
| Warranty | >80% capacity, up to 10 years or 6000 cycles |

## API energy stats fields

From `/device/queryDataElectricityV2` (daily scope, 2026-04-06):

| Field | Value | Description |
| --- | --- | --- |
| `gridelectricityfrom` | 5.86 kWh | Grid import (energy pulled from grid) |
| `gridelectricityto` | 13.4 kWh | Grid export (energy sent to grid) |
| `gridelectricity` | 13.4 kWh | Appears to equal `gridelectricityto`, not net |
| `solarelectricity` | 23.98 kWh | Total solar generation |
| `backupelectricity` | 14.06 kWh | Load on backup panel |
| `smarthomeelectricity` | 14.06 kWh | Total home load |
| `selfhelprate` | 59.0 | Self-sufficiency percentage |
| `treenum` | 0.77 | CO2 offset in trees equivalent |
| `coal` | 5.62 | CO2 offset in kg coal equivalent |

Fields with zero values (not connected): `generatorelectricity`,
`evelectricity`, `nonbackupelectricity`, `solardcelectricity`,
`solaracelectricity`, all extension port fields.

The stats endpoint also returns real-time power fields (all zero in the
response, likely stale or only populated for certain scope types).

Scope types: 0 = annual, 1 = daily, 2 = monthly, 3 = yearly detail.

## Simulation assumptions

These values are used in `replay_strategy.py` for strategy comparison:

| Parameter | Simulation value | Datasheet basis |
| --- | --- | --- |
| Charge efficiency | 0.92 | Per-leg estimate (inverter + battery) |
| Discharge efficiency | 0.92 | Per-leg estimate (inverter + battery) |
| Max charge per hour | 7.6 kWh | 7.6 kW continuous at 240V |
| Max discharge per hour | 7.6 kWh | 7.6 kW continuous at 240V |
| Battery capacity | 20.0 kWh | Config (app reports 19.98) |

Using 0.92 per leg (0.8464 round-trip). The inverter CEC rating is
93.93% per pass but real-world efficiency is lower due to partial load,
standby losses, and battery internal resistance. 0.92 per leg is a
conservative estimate that penalizes battery cycling appropriately --
strategies that cycle more will show realistic losses.
