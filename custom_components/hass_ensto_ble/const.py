"""Constants for the Hass Ensto BLE integration."""
from datetime import timedelta

# Domain identifier for Home Assistant
DOMAIN = "hass_ensto_ble"

# Scan interval in seconds for the number.py, sensor.py, select.py and switch.py
SCAN_INTERVAL = timedelta(seconds=30)

# Device specific constants
MANUFACTURER_ID = 0x2806  # Ensto manufacturer ID (big endian)

# Error codes for alarm status
ERROR_CODES_BYTE0 = {
    0x01: "Sensor fault (short-circuit)",
    0x02: "Low limit in combination mode",
    0x04: "High limit in combination mode",
    0x08: "Invalid vacation configuration",
    0x10: "Invalid calendar configuration",
    0x20: "Floor sensor missing",
    0x40: "Floor sensor broken",
    0x80: "Room sensor missing"
}

ERROR_CODES_BYTE1 = {
    0x01: "Room sensor broken",
    0x02: "Combination mode faulty set values (<8)",
    0x04: "Day calendar is not set"
}

# Device operation modes
ACTIVE_MODES = {
    1: "Manual",
    2: "Calendar",
    3: "Vacation"
}

# Heating modes for different device models
MODE_MAP = {
    1: "Floor",        # Floor sensor based heating (ECO16 only)
    2: "Room",         # Room sensor based heating
    3: "Combination",  # Combined floor and room (ECO16 only)
    4: "Power",        # Direct power control
    5: "Force Control" # Manual control mode
}

# Define supported modes per device model using mode numbers for direct lookup
SUPPORTED_MODES_ECO16 = {1, 2, 3, 4}
SUPPORTED_MODES_ELTE6 = {2, 4}

# Floor sensor types (only the ones in Ensto app) and parameter values (as written to device by Ensto app)
FLOOR_SENSOR_CONFIG = {
    "10 kΩ": {
        "sensor_type": 2,
        "sensor_missing_limit": 4007,
        "sensor_b_value": 3800,
        "pull_up_resistor": 47000,
        "sensor_broken_limit": 100,
        "resistance_25c": 10000,
        "offset": -1
    },
    "12 kΩ": {
        "sensor_type": 3,
        "sensor_missing_limit": 4007,
        "sensor_b_value": 3600,
        "pull_up_resistor": 47000,
        "sensor_broken_limit": 100,
        "resistance_25c": 12000,
        "offset": -7
    },
    "15 kΩ": {
        "sensor_type": 4,
        "sensor_missing_limit": 4007,
        "sensor_b_value": 3400,
        "pull_up_resistor": 47000,
        "sensor_broken_limit": 100,
        "resistance_25c": 15000,
        "offset": -5
    },
    "33 kΩ": {
        "sensor_type": 6,
        "sensor_missing_limit": 4007,
        "sensor_b_value": 4100,
        "pull_up_resistor": 47000,
        "sensor_broken_limit": 100,
        "resistance_25c": 33000,
        "offset": -4
    },
    "47 kΩ": {
        "sensor_type": 7,
        "sensor_missing_limit": 4007,
        "sensor_b_value": 3850,
        "pull_up_resistor": 47000,
        "sensor_broken_limit": 100,
        "resistance_25c": 47000,
        "offset": -8
    }
}

# Currency code mapping for energy unit
CURRENCY_MAP = {
    1: "EUR",  # Euro
    2: "SEK",  # Swedish Krona
    3: "NOK",  # Norwegian Krone
    4: "RUB",  # Russian Ruble
    5: "USD"   # United States Dollar
}

# Optional: Currency symbols for display purposes
CURRENCY_SYMBOLS = {
    1: "€",    # Euro
    2: "kr",   # Swedish Krona
    3: "kr",   # Norwegian Krone
    4: "₽",    # Russian Ruble
    5: "$"     # United States Dollar
}

# Device GATT service UUIDs
# 2.1.1. Manufacturer name string
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"

# 2.1.2. Device name
DEVICE_NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"
"""
Length 25 characters – default ‘Null’, mobile app presumes “New-Device”. 60 bytes long.
"""

# 2.1.3. Model number
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"

# 2.1.4. Software Revision String
SOFTWARE_REVISION_UUID = "00002a28-0000-1000-8000-00805f9b34fb"
"""
- application number is ascii followed by
semicolon (max size 7 + semicolon)
- BLE stack version is also ascii, followed
by semicolon
- bootloader version is 32bit (4 bytes)
long hex-value
"""
# 2.1.5. Manufacturing date
MANUFACTURING_DATE_UUID = "00002a85-0000-1000-8000-00805f9b34fb"
"""
BYTE[0]: uint8 day
BYTE[1]: uint8 month
BYTE[2-3]: uint16 year
"""

# 2.1.6. Hardware Revision String
HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
"""
BYTE[0-3]: uint32_t HW-version
"""

# 2.2.2. Date and time
DATE_AND_TIME_UUID = "b43f918a-b084-45c8-9b60-df648c4a4a1e"
"""
BYTE[0-1]: year 0…9999
BYTE[2]: month 1…12
BYTE[3]: date 1…31
BYTE[4]; hour 0…23
BYTE[5]: minute 0…59
BYTE[6]: second 0…59
"""

# 2.2.3. Day-light saving configuration
DAYLIGHT_SAVING_UUID = "e4f66642-ed89-4c73-be57-2158c225bbde"
"""
BYTE[0]: 1=enabled, 0=disable
BYTE[1]: reserved
BYTE[2-3]: offset int16_t (+-) for winter to
summer time as hours, compared to CET
BYTE[4-5]: offset int16_t (+-) for summer to
winter time as hours, compared to CET
BYTE[6-7]: timezone offset (int16) minutes
"""

# 2.2.4. Heating mode
HEATING_MODE_UUID = "4eb1d6a2-19e0-4809-ba55-4a94e7d9b763"
"""
ECO16:
BYTE[0]: 1=Floor, 2=Room, 3=Combination, 4=Power, 5= force control

ELTE6:
BYTE[0] 2 =Room, 4=power, 5= force control.
"""

# 2.2.5. Boost
BOOST_UUID = "ca3c0685-b708-4cd4-a049-5badd10469e7"
"""
BYTE[0] Boost 0=disabled, 1=enabled
BYTE[1-2]: Boost offset int16_t as degrees (Expected range: -20 to 20°C -20 → -2000, 20 → 2000)
BYTE[3]: Boost offset int8_t percentage
BYTE[4-5]: Boost time set point in minutes uint8_t
BYTE[6-7]: Boost time in minutes uint8_t, returns remaining boost time
"""

# 2.2.6. Power control cycle
POWER_CONTROL_CYCLE_UUID = "2cdb1af8-3f3d-4504-b56e-69a2532bc0b8"
"""
Cycle can be between 30 – 180 minutes.
BYTE[0]: power cycle - value 30 - 180
"""

# 2.2.7. Floor limits
FLOOR_LIMITS_UUID = "89b4c78f-6d5e-4cfa-8e81-4eca9738bbfd"
"""
This value is used only in the combination mode. Sets the minimum and maximum limit for
thermostat. Minimum must be always lower than 8 degrees from maximum limit. Maximum must be
always 8 degrees higher than the minimum limit. Invalid parameters are not taken into use.
Application can validate parameters if reading actually used parameters back from MCU.
Notice that there are certain max and min limits for these set points in the software, see technical
specification.

BYTE[0-1]: Low value
ECO16: Default setting 10 C (10,00 is 1000)
ELTE6: Do not care
BYTE[2-3]: High value
ECO16: Default setting 45 C (45,00 is 4500)
ELTE6: Do not care
"""

# 2.2.8. Child lock
CHILD_LOCK_UUID = "6e3064e2-d9a5-4ca0-9d14-017c59627330"
"""
Default value for Eco16: OFF
Child lock is not used as a security feature. This provides “memory register” for application to maintain
value for enable/disable and lock value.

BYTE[0] 1=on, 0=off
BYTE[1-2], uint16_t, value as 0-9999

Read: get current state on/off
Write: set current state

"""

# 2.2.9. Adaptive temperature control
ADAPTIVE_TEMPERATURE_CONTROL_UUID = "c2dc85e9-47bf-4968-9562-d2e1980ed4e4"
"""
BYTE[0] 1=on, 0=off
"""

# 2.2.10. Floor sensor type
FLOOR_SENSOR_TYPE_UUID = "f561ce1f-61fb-4fa2-8bef-5fecc949b55b"
"""
Application can configure floor sensor behavior with floor sensor parameters. Typically there can be
following sensors like 6k, 8k, 10k, 12k, 15k, 33k and 47k.
Memory slot for application – not used by thermostat.

Floor sensor configuration
BYTE[0]: sensor type which can be read and
written by application
1 = 6,8kOhm
2 = 10kOhm
3 = 12kOhm
4 = 15kOhm
5 = 20kOhm
6 = 33kOhm
7 = 47kOhm

BYTE[1-2]: sensor missing limit adc (uint16)
BYTE[3-4]: Sensor B - value
BYTE[5-6]: Pull-Up resistor(uint16)
BYTE[7-8]: sensor broken limit adc(uint16)
BYTE[9-10]: Resistance at 25C (uint16)
BYTE[11-12]: Offset (int16) -0,1 = -1 etc
"""

# 2.2.11. Heating power
HEATING_POWER_UUID = "53b7bf87-6cf0-4790-839a-e72d3afbec44"
"""
Set custom heating power.
Memory slot for application – not used by thermostat.

BYTE[0-1], uint16_t, value as 0-9999
"""

# 2.2.12. Floor area to heat
FLOOR_AREA_UUID = "5c897ab6-354c-443d-9f36-f3f7263868dd"
"""
BYTE[0-1], uint16_t, floor area number specified by application
"""

# 2.2.13. Calibration value for room temperature
CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID = "1eca4351-b264-4db6-9c59-af4341d6ce69"
"""
BYTE[0-1]: int8_t, range -50-+50, scaled to -5 - +5, only used in application

value = (BYTE[0] + 256 * BYTE[1]) / 10
"""

# 2.2.14. Led brightness
LED_BRIGHTNESS_UUID = "0bee30ff-ed95-4747-bf1b-01a60f5ff4fc"
"""
Led brightness can be set from application for each led.
Default value for Eco16: 50%

BYTE[0]: uint8_t, value as 0-100 for RED
BYTE[1]: uint8_t, value as 0-100 for GREEN
BYTE[2]: uint8_t, value as 0-100 for BLUE
"""

# 2.2.15. Energy unit
ENERGY_UNIT_UUID = "ccf1fe7b-d928-45b1-abba-7a915f2f0c64"
"""
Energy unit characteristic is not used by the thermostat, but is used solely by the mobile application.

BYTE [0]: (unsigned byte) User selected currency. Example values e.g. EUR = 1, SEK = 2, NOK = 3, RUB = 4, USD = 5
BYTE [1]: Unused
BYTE [2-3]: (unsigned word) Price of single energy unit scaled by multiplier of 100.
For example price 1.2 is stored as number 120 in MCU.
"""

# 2.2.16. Alarm code
ALARM_CODE_UUID = "644b0534-cdc5-4538-8ba5-1408df8849d4"
"""
BYTE[0]:
0x01 = SENSOR FAULT (short-circuit on)
0x02 = LOW LIMIT Combination mode
0x04 = HIGH LIMIT Combination mode
0x08 = Invalid vacation configuration
0x10 = Invalid calendar configuration
0x20 = Floor sensor missing
0x40 = Floor sensor broken
0x80 = Room sensor missing
BYTE[1]:
0x01 = Room sensor broken
0x02 = Combination mode faulty set values <8
0x04 = Day calendar is not set
0x08 =
BYTE[2]:
0x01 = reserved
0x02 = reserved
0x04 = reserved
0x08 = reserved
BYTE[3]:
0x01 = reserved
0x02 = reserved
0x04 = reserved
0x08 = reserved
"""

# 2.2.17. Calendar control characteristics
CALENDAR_CONTROL_UUID = "8219bc38-a505-4452-8b6c-165e75cff5db"
"""
This characteristics is for writing the number of day that is requested from thermostat.

Value is a day number and thermostat writes
corresponding day control settings to day
control settings characteristics 1 – 7
BYTE[0]: uint8_t day number, 0-255
- thermostat gets day number 1 – 7
- writing 0 requests thermostat to store data to flash
- writing 8 tells that name of the calendar is next write to be written
"""

# 2.2.18. Calendar day
CALENDAR_DAY_UUID = "20db94b9-bd18-4f84-bf16-de1163adfd8c"
"""
This characteristics returns requested day, which is set in calendar control characteristics. If user
requested name for calendar then 8 must be set to control characteristics. Cyrillic and normal names
have 60 bytes. If user stores any day to thermostat the format is same and writing is done here, no
control characteristics needed for writing operation.
This message is sent to mobile app in split format.

For each day:
(wall clock used to check times)
BYTE[0]: control characteristics request number
uint8_t value >0
Following dataset is here six times, because
each day has 6 different programs to be set:
BYTE[n+0]: time from, hour 0 - 23
BYTE[n+1]: time from, minute 0-59
BYTE[n+2]; time to, hour 0-23
BYTE[n+3]: time to, minute 0-59
BYTE[n+4- n+5]: offset temperature, int16_t -
20 - +20 -> 20,5 as 2050
BYTE[n+6]: offset percentage, int8_t
-100 – 100 %
BYTE[n+7]: 0=disable, 1=enable
Total bytes for day: 1 + 6 * 8 bytes = 49 bytes

For calendar name format is as follows:
BYTE[0]: 0x08
BYTE[1-60]: calendar name

NOTE! Split to several messages
"""

# 2.2.19. Vacation time
VACATION_TIME_UUID = "6584e9c6-4784-41aa-ac09-c899191048ae"
"""
If this is found in settings it overrides other offset setters in mcu.
Default time is 1.7.2016 – 1.8.2016

Vacation time, “wall clock” time
BYTE[0]; time from, year 0-255
BYTE[1]: time from, month 1-12
BYTE[2]: time from, date 1-31
BYTE[3]; time from, hour 0-23
BYTE[4]: time from, minute 0-59
BYTE[5]; time to, year 0-255
BYTE[6]: time to, month 1-12
BYTE[7]: time to, date 1-31
BYTE[8]; time to, hour 0-23
BYTE[9]: time to, minute 0-59
BYTE[10-11]: offset temperature, int16_t -20 - +20
BYTE[12]: offset percentage int8_t, 0-100%
BYTE[13]: 0=disable, 1=enable
BYTE[14]: vacation mode: 1 = on/0 = off, read only for current vacation mode state

NOTE! Split to several messages
"""

# 2.2.20. Calendar mode
CALENDAR_MODE_UUID = "636d45fd-d7be-491f-966c-380f8631b2c6"
"""
BYTE[0] 1=calendar used, 0=calendar not used
"""

# 2.2.21. Device factory reset ID
FACTORY_RESET_ID_UUID = "f366dddb-ebe2-43ee-83c0-472ded74c8fa"
"""
BYTE[0-3]: uint32_t factory reset ID
Characteristics UUID value BYTE[4-9]: mac address of the device

Read: Returns 0 if not in device pairing/bonding
phase, otherwise provide the internal pseudo-
random factory reset id.
Write: request authentication from MCU with
factory reset ID which was received during
device registration phase
"""

# 2.2.22. Monitoring data
MONITORING_DATA_UUID = "ecc794d2-c790-4abd-88a5-79abf9417908"
"""
Phone application requests monitoring data with the following characteristics and MCU sends the
measurement buffer using the specified long message format. Notifications from MCU ends
automatically when all requested data is sent. On/off ratio in the following table means on/off ratio
for TRIAC and relay in corresponding thermostat.
Monitoring data storing in mcu uses local time, so called wall clock time. So nothing here is at utc
time. If values are not set they are 0xff. If temperature values are not set they are 0x7fff.

On/off ratio of last 7 days, each:
HEADER – wall clock stamp
- BYTE[0]: uint8 day
- BYTE[1]: uint8 month
- BYTE[2]: uint8 year (0-255)
DATA
- BYTE[D0]:uint8_t delta day from header
- BYTE[D1]: uint8_t, Ratio 0-100
if hibernation was set over this, day normally and ratio = 0
On/off ratio of last 12 months + cumulative,
each:
HEADER - wall clock stamp
- BYTE[0]: uint8 month
- BYTE[1]: uint8 year (0-255)
DATA
- BYTE[D0]:uint8_t, delta month from header
- BYTE[D1]:uint8_t, Ratio 0-100
if hibernation is set over this, month =
normally and ratio 0
Hourly floor and room temperature over week
(24 hours/7days), each:
HEADER: - wall clock stamp
- BYTE[0]: uint8 hour
- BYTE[1]: uint8 day
- BYTE[2]: uint8 month
- BYTE[3]: uint8 year (0-255)
DATA:
- BYTE[0]: delta hour from header
- BYTE[4-5]: int16_t, floor temp
- BYTE[6-7]: int16_t, room temp
range -50-500, scaled to -5.0 to 50.0
if hibernation set over hour,
temperatures are 0
Temperature: 4+5*168 = 844
day consume: 3 + 8 * 2 = 19
month consume: 2 + 13 * 2 = 28
Total: 844 + 19 + 28 = 891
"""

# 2.2.23. Real Time Indication temperature and mode
REAL_TIME_INDICATION_UUID = "66ad3e6b-3135-4ada-bb2b-8b22916b21d4"

# 2.2.24. Real time indication power consumption
REAL_TIME_INDICATION_POWER_CONSUMPTION_UUID = "c1686f28-fa1b-4791-9eca-35523fb3597e"
"""
This is data to be advertised when client is idle – not sending/reading settings data of thermostat.
Thermostat stores last 25 hours and last 7 days. Updates once/second. If values are not set they are
0xff.

Last 25 hours
HEADER: - wall clock stamp
- BYTE[0]: uint8 hour
- BYTE[1]: uint8 day
- BYTE[2]: uint8 month
- BYTE[3]: uint8 year (0-255)
DATA:
- BYTE[d0]; delta hour from header,0 is
current
- BYTE[d1]: Ratio 0-100
total: 4 + 25*2 = 54

Parsing of this data is done as follows:
- Get header value – is uint32_t and has value hours passed from epoch time in it (1.1.2016)
- Next get two byte values: (First pair is current hour)
Value 1: epoch hours minus this is timestamp for current measurement
Value 2: ratio, this is the power consumption ratio for hour at hand

For example:
Mcu local time is 05:00 1.1.2016 and measurement is sent:
Bytes Header (hours from epoch)
0-3 Epoch = 5
Timestamp (calculate) Value 1 (delta hours) Value2 Ratio (0-100)
4-5 5 0 90
5-6 4 1 89
7-8 3 2 90
9-10 2 3 90
11-12 1 4 90
13-14 0 5 90

"""

# 2.2.25. Force control
FORCE_CONTROL_UUID = "7bd74f74-ffae-452e-bb61-b59b2faf96c9"
"""
Force control characteristic is for setting desired potentiometer value to thermostat.
This brings new mode into heating mode parameters. When this mode is set, then no other modes are used.
MCU physical potentiometer is ignored in this mode. Target %-value change is immediate.

BYTE[0]: potentiometer setpoint 0-100%, uint8
"""
