# Bluetooth Proxies

A Bluetooth proxy extends Bluetooth range by connecting thermostats to Home Assistant over your network. It is often more reliable than the Bluetooth adapter on the Home Assistant host.

> **Note:** Only ESPHome Bluetooth proxies (ESP32) can connect to thermostats. Shelly and SMLIGHT proxies only listen for advertisements and do not work with this integration. See the [Home Assistant Bluetooth documentation](https://www.home-assistant.io/integrations/bluetooth/#remote-adapters-bluetooth-proxies).

## Recommended Hardware

Use an Ethernet ESP32 board with an external antenna, as recommended by [ESPHome](https://esphome.io/components/bluetooth_proxy/). On an ESP32, Wi-Fi and Bluetooth share the same radio, so a wired Ethernet connection leaves the radio free for Bluetooth.

**Tested boards:**
- **Olimex ESP32-POE-ISO-EA** (Ethernet, external antenna) – works reliably with three thermostats on one proxy
- **Olimex ESP32-POE-ISO** (Ethernet, no external antenna) – works reliably with three thermostats on one proxy, but the signal is weaker than with an external antenna when the thermostats are further away
- **ESP32-WROOM-32** (Wi-Fi) – not recommended: connections dropped repeatedly even with a single thermostat

> **Note:** PoE is not required. The Olimex boards can also be powered via USB.

## Setup

1. Install the proxy firmware from the [ESPHome Ready-Made Projects](https://esphome.io/projects/?type=bluetooth) page, or with your own ESPHome configuration. Wired boards, such as the Olimex, have Wi-Fi disabled, so connect the Ethernet cable first
2. Use ESPHome 2026.10.2 or newer
3. Add the proxy to Home Assistant via **Settings → Devices & services**. If it is not discovered automatically, add the **ESPHome** integration manually with the proxy's IP address and its API encryption key
4. Place the proxy close to the thermostats
5. Pair the thermostats as usual, see [Pairing a Thermostat](../README.md#pairing-a-thermostat)

**Keep in mind:**
- Each thermostat uses one of the proxy's connection slots. ESPHome's default is 3 slots, and Ethernet boards, such as the Olimex, can handle 4
- Moving thermostats to a new proxy does not require pairing them again. To avoid connection errors while you replace the board, disable the thermostats in Home Assistant first and enable them again once the new proxy is added
- Some Ensto products, such as electric heaters, have a metal casing, which weakens their Bluetooth signal considerably. Place the proxy close to them

## Troubleshooting Proxies

**Thermostat shows "Device not found":**
1. Update the proxy to ESPHome 2026.10.2 or newer. Older versions can block reconnecting after a connection drop
2. Restart the proxy or power-cycle the thermostat

## Debug Logging

Add the following to `configuration.yaml` and restart Home Assistant:

    logger:
      default: warning
      logs:
        custom_components.hass_ensto_ble: info
        habluetooth: debug
        bleak_retry_connector: debug
        bleak_esphome: debug
        aioesphomeapi.connection: debug

Remove the debug lines when you are done, as they produce a lot of log data.
