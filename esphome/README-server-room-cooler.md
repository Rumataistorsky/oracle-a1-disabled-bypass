# Server room cooling — dual Noctua NF-A15 + ESP32

Push-pull ventilation for the basement server room: one fan blows cold air in,
one pulls hot air out, three DS18B20 probes decide how hard they work.

## Bill of materials

| Part | Notes |
|---|---|
| ESP32 DevKit (Elegoo, micro-USB) | 38-pin, `board: esp32dev` |
| 2x Noctua NF-A15 HS-PWM chromax | 12 V, 0.13 A, 1.56 W each — 0.26 A total |
| 3x DS18B20 | waterproof probe version is easiest to route |
| 1x 4.7 kOhm resistor | single pull-up for the whole 1-Wire bus |
| 12 V PSU, >= 1 A | fans + headroom |
| Mini360 buck 12 V -> 5 V | feeds ESP32 VIN |
| 2x 4-pin fan extension cable | cut one end, keep the connector |

## Wiring

```
12V PSU +12V ──┬── fan1 pin2 (yellow)   fan pin1 GND (black) ──┐
               ├── fan2 pin2 (yellow)                          │
               └── Mini360 IN+                                 │
Mini360 OUT+ (5V) ── ESP32 VIN                                 │
12V PSU GND ───────── ESP32 GND ── Mini360 IN-/OUT- ───────────┘

ESP32 GPIO25 ── fan IN  pin4 PWM (blue)
ESP32 GPIO26 ── fan OUT pin4 PWM (blue)
ESP32 GPIO32 ── fan IN  pin3 TACH (green)
ESP32 GPIO33 ── fan OUT pin3 TACH (green)
ESP32 GPIO4  ── DS18B20 data (all three in parallel) ── 4.7k ── 3V3
ESP32 3V3    ── DS18B20 VDD (all three)
ESP32 GND    ── DS18B20 GND (all three)
```

Everything shares one ground. GPIO 0/2/12/15 are strapping pins and 34-39 have no
internal pull-up, so none of them are used here.

Noctua's PWM input takes 3.3 V push-pull at 25 kHz without trouble. If a fan
refuses to drop below ~40 % or stutters, add a 3.3 -> 5 V level shifter on the
PWM lines only — the tacho lines are open-drain and must stay on 3.3 V.

## Probe placement

| Probe | Where | Why |
|---|---|---|
| `t_intake` | at the intake fan, outside air | reference for Delta T |
| `t_exhaust` | at the exhaust fan, hot side | what the room actually exhausts |
| `t_case` | taped to the server chassis, top rear | the thing being protected |

`Delta T` (exhaust minus intake) is the useful diagnostic: a rising delta at
constant duty means airflow is being lost — clogged filter, dead fan, blocked
inlet.

## Flashing

1. Add the secrets used here to `/config/esphome/secrets.yaml` on HA-OS VM 101:
   `server_room_cooler_api_key`, `ota_password`, `wifi_ssid`, `wifi_password`,
   `fallback_password`.
2. Copy `server-room-cooler.yaml` into `/config/esphome/`, flash over USB the
   first time, OTA after that.
3. Run `esphome logs server-room-cooler.yaml` — it prints the address of each
   DS18B20 found on the bus. Paste the three addresses into the `address:`
   fields (unplug probes one at a time to tell which is which), then re-flash.

## Control logic

Linear curve on whichever of case/exhaust reads hottest:

- below `Curve Start Temp` (26 °C default) -> `Minimum Duty` (20 %)
- above `Curve Full Temp` (38 °C default) -> 100 %
- in between -> linear ramp
- any probe reading NaN -> 100 % (failsafe)
- intake runs at exhaust duty + `Intake Offset` (10 %) to keep the room at
  slight positive pressure, so air enters through the filtered inlet instead of
  every gap in the room
- `Auto Curve` off -> `Manual Duty` drives both fans

Tune the numbers from Home Assistant; they survive reboots.
