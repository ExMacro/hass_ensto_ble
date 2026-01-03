![GitHub Release](https://img.shields.io/github/v/release/ExMacro/hass_ensto_ble)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/ExMacro/hass_ensto_ble)
![GitHub License](https://img.shields.io/github/license/ExMacro/hass_ensto_ble)
[![Installs](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=installs&suffix=%20total&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.hass_ensto_ble.total)](https://github.com/ExMacro/hass_ensto_ble)

# Hass Ensto BLE

Custom component to read and write data from Ensto BLE thermostats.

## Compatibility

- **Tested environment:** Raspberry Pi 4, Home Assistant OS 16.3, Supervisor 2025.12.3, Core 2025.12.5
- **Supported devices:** Ensto ELTE6-BT, ECO16BT, and EPHE5-BT thermostats (should work with all Ensto thermostats supporting the same BLE Interface Description)
- **Multi-device support:** Works with multiple thermostats and ESP32 Bluetooth proxies
- **Installation type:** Developed and tested only with Home Assistant OS. Other installation types are not guaranteed to work.

> **Note:** This is a hobby project under active development.

## Installation

### HACS

1. Search for `HASS Ensto BLE` in HACS default repositories
2. Download the latest release
3. Restart Home Assistant
4. Navigate to **Settings → Devices & services → Add Integration**
5. Search for "Hass Ensto BLE"

## Initial Setup

### Pairing a Thermostat

1. Put the thermostat in pairing mode (hold BLE reset button >0.5 seconds until blue LED blinks)
2. Select your thermostat from the discovered devices list
3. Choose currency for energy calculations (stored in thermostat memory)

### Adding Thermostat to Dashboard

1. Navigate to **Settings → Devices & services → Helpers → Create helper**
2. Select **Generic thermostat** and configure:
   - **Temperature sensor:** Select floor or room temperature sensor
   - **Actuator switch:** Select "Boost Mode" switch
   - **Cold/Hot tolerance:** 0.5 is recommended
3. Click **Next → Submit → Finish**
4. Add a Thermostat card to your dashboard using the new climate entity

## Features

### Heating Mode

Configure the thermostat's heating mode.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Heating mode** selector
3. Select a mode from the dropdown menu

**Available modes** (not all thermostats support all modes):
- **Floor** – Floor sensor based heating (ECO16 only)
- **Room** – Room sensor based heating
- **Combination** – Combined floor and room sensors (ECO16 only)
- **Power** – Direct power control

> **Note:** Floor temperature min/max values are only used in Combination mode. Boost power offset and vacation power offset are only used in Power mode.

### Boost Mode

Temporarily increase the temperature for a specified duration.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Configure the following:
   - **Boost duration** – Duration in minutes
   - **Boost temperature offset** – Offset from -20°C to +20°C (or **Boost power offset** from -100% to +100% in Power mode)
3. Enable the **Boost mode** switch
4. The **Boost remaining** sensor shows the countdown to zero, then automatically disables

### Adaptive Temperature Control

Enable the thermostat's built-in adaptive temperature adjustment.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Adaptive temperature control** switch
3. Toggle on or off as needed

### Daylight Saving

Configure automatic daylight saving time adjustments.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Daylight saving** switch
3. Toggle on or off as needed

The device automatically converts between UTC and local time based on this setting.

### Device Time Synchronization

Synchronize the thermostat's internal clock with Home Assistant.

Home Assistant shows a notification if the device time differs by more than one minute.

1. Navigate to **Developer Tools → Actions**
2. Select service `hass_ensto_ble.set_device_time`
3. Select your thermostat's DateTime entity as target
4. Click **Perform action**
5. Verify the **Date and time** sensor shows the correct local time

The notification disappears automatically once synchronized.

> **Note:** Time is handled internally in UTC to ensure consistent operation across time zones.

### Floor Sensor Type

Change the floor sensor type for accurate temperature readings (ECO16 only).

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Floor sensor type** selector
3. Select the appropriate sensor type from the dropdown menu

The thermostat will return updated temperature values based on the new sensor type.

### Floor Temperature Limits

Configure minimum and maximum floor temperature limits (ECO16 only, Combination mode).

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Floor temperature min** and **Floor temperature max** entities
3. Adjust values as needed

**Constraints:**
- Minimum must be at least 8°C lower than maximum
- These settings are only active in Combination heating mode
- Entities are disabled in other heating modes

### Room Sensor Calibration

Calibrate the room temperature sensor for accurate readings.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Room sensor calibration** entity
3. Set a value between -5.0°C and +5.0°C

Positive values increase the displayed temperature; negative values decrease it.

### Heating Power

Configure the thermostat's heating power rating for energy calculations.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Heating power** entity
3. Set your thermostat's actual power rating (e.g., 900W)

This value is stored in the thermostat's memory and enables power consumption monitoring.

### Floor Area

Configure the heated floor area for reference (ECO16 only).

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Floor area** entity
3. Set the floor area in square meters

This value is stored in the thermostat's memory.

### Energy Monitoring

Monitor power usage and historical data.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Power usage** sensor

The sensor includes the following attributes:
- Last 24-hour thermostat on/off ratio
- Last 7-day thermostat on/off ratio
- Last 12-month thermostat on/off ratio
- Hourly floor and room temperature history

### Real-Time Power Consumption

Monitor real-time power consumption and track energy usage.

**Setup:**

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Set your thermostat's power rating in the **Heating power** entity
3. The **Current power** sensor becomes available showing:
   - Full heating power when the relay is ON
   - 0W when the relay is OFF

### Vacation Mode

Schedule a vacation period with reduced temperature.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Configure the following:
   - **Vacation start** and **Vacation end** – Date and time
   - **Vacation temperature offset** – Offset from -20°C to +20°C (or **Vacation power offset** from -100% to +100% in Power mode)
3. Enable the **Vacation mode** switch

The thermostat automatically activates and deactivates vacation mode at the configured times.

### Calendar Mode

Enable weekly scheduling for automated temperature control.

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **Calendar mode** switch
3. Toggle on to activate weekly scheduling, off for manual control

When enabled, the thermostat follows programmed weekly schedules instead of manual temperature settings.

#### Reading Calendar Programs

1. Navigate to **Developer Tools → Actions**
2. Select service `hass_ensto_ble.get_calendar_day`
3. Select any of your thermostat's sensor entities as target
4. Enter the day number (1=Monday, 7=Sunday)
5. Click **Perform action**

#### Writing Calendar Programs

1. Navigate to **Developer Tools → Actions**
2. Select service `hass_ensto_ble.set_calendar_day`
3. Select any of your thermostat's sensor entities as target
4. Configure the day and up to six programs:

```yaml
- start_hour: 6
  start_minute: 0
  end_hour: 8
  end_minute: 30
  temp_offset: 2.0
  power_offset: 0
  enabled: true
- start_hour: 17
  start_minute: 0
  end_hour: 22
  end_minute: 0
  temp_offset: 1.5
  power_offset: 0
  enabled: true
```

5. Click **Perform action**

### External Control

Control the thermostat via external input signal.

**Requirements:**
- Firmware version 1.14 or newer
- External control wiring connected to the thermostat (see Ensto documentation)

**Configuration:**

1. Navigate to **Settings → Devices & services → [Your thermostat]**
2. Find the **External control mode** selector with options:
   - **Off** – External control disabled
   - **Temperature** – Set absolute target temperature
   - **Temperature change** – Set temperature offset from normal target
3. Configure the corresponding value:
   - **External control temperature** (5°C to 35°C) when using Temperature mode
   - **External control offset** (-20°C to +20°C) when using Temperature change mode

## Troubleshooting

### Pairing Issues

Some users need additional pairing via terminal to establish a Bluetooth connection.

1. Open the Home Assistant terminal
2. Run `bluetoothctl` (you can continue entering commands while Bluetooth messages appear)
3. If you previously added the thermostat and then paired it to another device, first run:
   ```
   remove XX:XX:XX:XX:XX:XX
   ```
4. Run the following commands (replace XX:XX:XX:XX:XX:XX with your device's MAC address):
   ```
   trust XX:XX:XX:XX:XX:XX
   pair XX:XX:XX:XX:XX:XX
   ```
5. Set your Ensto thermostat to pairing mode (blue LED blinking)
6. Proceed with adding the thermostat in Home Assistant

### Time Sync Issues

Incorrect internal time (e.g., years in the future or past) is commonly caused by a weak or dead RTC backup battery.

1. Replace the CR1225 battery (see device installation manual)
2. Use the `set_device_time` service in Developer Tools to synchronize the time

## Known Limitations

### Device Name Writing (Home Assistant OS 16.2+)

Device names cannot be changed via Home Assistant on systems using BlueZ 5.82 or newer (Home Assistant OS 16.2+).

**Cause:** BlueZ 5.82+ enforces strict Bluetooth standards and blocks client-side writes to GAP (Generic Access Profile) characteristics, including UUID 2A00 (Device Name).

**Workaround:** Use Ensto's official mobile application (iOS/Android) to change the device name. The integration reads and displays the device name in Home Assistant.
