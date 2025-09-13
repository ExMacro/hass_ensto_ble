![GitHub Release](https://img.shields.io/github/v/release/ExMacro/hass_ensto_ble)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/ExMacro/hass_ensto_ble)
![GitHub License](https://img.shields.io/github/license/ExMacro/hass_ensto_ble)
[![Installs](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=installs&suffix=%20total&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.hass_ensto_ble.total)](https://github.com/ExMacro/hass_ensto_ble)

# hass_ensto_ble
_Custom component to read and write data from Ensto BLE thermostats._

## Note
- Integration is tested on Raspberry PI 4, Home Assistant OS 16.2, Supervisor 2025.09.0, Core 2025.9.2.
- Integration tested with Ensto ELTE6-BT and ECO16BT thermostats but should work with all Ensto thermostat supporting the same BLE Interface Description.
- The integration works with multiple thermostats and ESP32 Bluetooth proxies.
- This is a hobby project under active development. Integration may not work with all HA installation types.

## Troubleshooting
### Pairing Issues
Some users have needed additional pairing in the terminal to establish a Bluetooth connection.

- In Home Assistant terminal, run bluetoothctl. You can continue entering commands while Bluetooth messages appear on screen.
- If you added the thermostat to HA before and then paired it to another device, you will probably have to remove XX:XX:XX:XX:XX:XX first
- First type trust XX:XX:XX:XX:XX:XX (replace with your device's MAC address)
- Second type pair XX:XX:XX:XX:XX:XX (replace with your device's MAC address)
- Set your Ensto BLE thermostat to pairing mode (blue light blinking)
- Proceed adding the Ensto BLE thermostat in Home Assistant

### Time Sync Issues
Common cause for the thermostats to display incorrect internal time (e.g., years in the future or past) is weak or dead RTC backup battery.
- See the device installation manual on replacing the CR1225 battery
- Set correct time using the set_device_time service in Developer Tools after battery replacement

## Installation
## HACS (Recommended)
1. Search the repository `HASS Ensto BLE` from HACS default repositories
2. Download the latest release to HACS
3. Restart HA
4. Go to Settings > Devices & services > Add Integration
5. Search for "Hass Ensto BLE"

## Manual installation

1. Navigate to your Home Assistant configuration directory (where `configuration.yaml` is located)
2. Create `custom_components/hass_ensto_ble` directory
3. Download and place all repository files in the directory
4. Restart Home Assistant
5. Add integration via Settings > Devices & services

## Setup Process
1. Put thermostat in pairing mode (hold BLE reset button >0.5 seconds until blue LED blinks)
2. Select your thermostat from the discovered devices list
3. Choose currency for energy calculations (stored in thermostat)

## Supported functions
### Naming the Ensto BLE thermostat

1. Navigate to Developer Tools > Services
2. Select service `hass_ensto_ble.set_device_name`
3. Select a thermostat name entity if you have multiple thermostats
4. Enter a new name in the Name field (maximum 25 characters)
5. Click "PERFORM ACTION"

The new name will be visible:
- In the Devices & services > Integrations page
- In the device card when you click on the device
- Please note that entity names for the device are not renamed

The name is stored directly in the thermostat's memory and persists through restarts.

### Setting heating mode
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Select a mode from the drop down menu.

All Ensto BLE thermostats do not support all modes.

Floor temperature min / max values are only used in the Combination heating mode.
Boost power offset and vacation power offset are only used in the Power heating mode

### Enable boost mode
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Set Boost duration in minutes
3. Set Boost temperature offset (-20C to 20C) or boost power offset (-100% to 100%) if you're using Power heating mode
4. Enable "Ensto Boost Mode"
5. Sensor "Ensto Boost Remaining" will start counting from set boost time to zero and turn off automatically.

### Enable adaptive temperature control
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Enable "Ensto Adaptive Temperature Control". Note! This is a simple switch to enable/disable adaptive temperature change on the device.

### Change the floor sensor type
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Change the Floor sensor type from the drop down menu
3. After a while, the thermostat will return a new temperature value based on the new floor sensor type

### Set the device time
1. Home Assistant shows a notification if the device time differs more than one minute from Home Assistant time
2. Time is handled internally in UTC to ensure consistent operation across time zones
3. To synchronize the time:
   - Go to Developer Tools > Actions
   - Select service `hass_ensto_ble.set_device_time`
   - Select your thermostat's DateTime entity
   - Click "PERFORM ACTION"
4. Navigate to Settings > Devices & services > [Your thermostat]
5. Verify that the DateTime sensor shows the correct local time
6. The notification will automatically disappear once the time is synchronized

The notification will automatically disappear once the time is synchronized.

### Setting Daylight saving

1. Navigate to Settings > Integrations > [Your Ensto thermostat] > Entities
2. Find the Daylight Saving switch
4. Turn the switch on or off as needed
   - The device will automatically convert between UTC and local time based on this setting

### Setting Floor Temperature Limits
1. Navigate to Settings > Integrations > [Your Ensto thermostat] > Entities
2. Find the Floor Min and Max Temperature
3. Adjust as needed
   - The minimum temperature must always be at least 8 degrees lower than the maximum limit
   - These settings are only used in combination heating mode
   - In other heating modes, the sensors will be disabled

### Setting Room Sensor Calibration value
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find the Room Sensor Calibration number entity
3. Set a value between -5.0°C and +5.0°C to calibrate the room temperature sensor
   - Positive values increase the displayed temperature
   - Negative values decrease the displayed temperature

### Setting Heating Power
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find the Heating Power entity
3. Adjust the power level

Changes are stored in the thermostat's memory

### Configuring Floor Area
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find the Floor Area entity
3. Set the floor area

Changes are stored in the thermostat's memory

### Comprehensive Energy Monitoring
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find the power usage sensor. It includes the following information as attributes:
   - Last 24 hour thermostat on/off ratio tracking
   - Last 7-day thermostat on/off ratio tracking
   - Last 12-month thermostat on/off ratio tracking
   - Hourly floor and room temperature readings

### Setting Vacation Mode
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find and configure the vacation end times
3. Configure the vacation temperature offset (-20C to 20C) or vacation power offset (-100% to 100%) if you're using Power heating mode
4. Enable the vacation mode switch. The thermostat will turn on the vacation mode on and off when the vacation start and end times are reached.

Temperature and power offset values and date settings will automatically update in the UI.

### Setting Calendar Mode
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find the Calendar Mode switch
3. Enable to activate weekly scheduling, disable for manual control

When calendar mode is enabled, the thermostat follows your programmed weekly schedule instead of manual temperature settings.

#### Reading Calendar Programs
1. Navigate to Developer Tools > Actions
2. Select service `hass_ensto_ble.get_calendar_day`
3. Select any of your thermostat's sensor entities
4. Enter day number (1=Monday, 7=Sunday)
5. Click "PERFORM ACTION"

#### Programming Calendar Days
1. Navigate to Developer Tools > Actions
2. Select service `hass_ensto_ble.set_calendar_day`
3. Select any of your thermostat's sensor entities
4. Configure the day and programs (up to six):

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
### Real-time Power Consumption Monitoring
1. Navigate to Settings > Devices & services > [Your thermostat]
2. Find the Heating Power entity and set your thermostat's actual power rating (e.g., 900W)
3. The Current Power sensor will become available and show:
   - Full heating power when the relay is ON
   - 0W when the relay is OFF
4. To track energy consumption (kWh):
   - Go to Settings > Helpers > Create Helper > Integral Sensor
   - Select your thermostat's Current Power sensor as input
   - Set Method to "Left Riemann sum" and Unit prefix to "kilo (k)"
   - The resulting kWh sensor can be added to Home Assistant's Energy Dashboard

This enables complete energy monitoring including real-time power usage, daily/monthly consumption tracking, and cost calculations.
