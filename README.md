# hass_ensto_ble
_Custom component to read and write data from Ensto BLE thermostats._

## Note
- This is an early development version. It's a hobby project and will be developed slowly for my own purposes. Please be patient.
- Currently this integration does not work with ESP32 bluetooth proxy
- Currently this integration supports a limited amount of functionality compared to Ensto Heat app
- Integration tested on Raspberry PI 4, Home Assistant OS 14.1, Supervisor 2024.12.3, Core 2025.1.4
- Integration tested with Ensto ELTE6-BT and ECO16BT thermostats but should work with all Ensto thermostat supporting the same BLE Interface Description

## Installation
1. Open the directory (folder) for your HA configuration (where you find configuration.yaml).
2. If you do not have a [custom_components folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) there, create it.
3. In the [custom_components folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) create a new folder called hass_ensto_ble.
4. Download all the files in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Hass Ensto BLE".
8. The integration will automatically detect if there is an Ensto BLE thermostat in pairing mode

## Supported functions
### Naming the Ensto BLE thermostat
1. Navigate to "Developer Tools" -> "Actions"
2. Select "Hass Ensto BLE: Set device name"
3. Write a new name for the device into the Name field. Note: maximum of 25 characters.
4. The device name will show in the "Integration entries" page in "Settings" -> "Devices & services" when you click the integration name

### Setting Ensto BLE thermostat heating mode
1. Navigate to "Settings" -> "Devices & services" and click on the device
2. Select a mode from the drop down menu. Note! All Ensto BLE thermostats do not support all modes.

### Enable boost mode on the Ensto BLE thermostat
1. Navigate to "Settings" -> "Devices & services" and click on the device
2. Set Boost duration in minutes
3. Set Boost temperature offset in Celsius
4. Enable "Ensto Boost Mode"
5. Sensor "Ensto Boost Remaining" will start counting from set boost time to zero and turn off automatically.

### Enable adaptive temperature control on the Ensto BLE thermostat
1. Navigate to "Settings" -> "Devices & services" and click on the device
2. Enable "Ensto Adaptive Temperature Control". Note! This is a simple switch to enable/disable adaptive temperature change on the device.

