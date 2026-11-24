"""Exceptions for Ensto BLE."""
from homeassistant.exceptions import HomeAssistantError


class EnstoBleError(HomeAssistantError):
    """A Bluetooth read or write to the thermostat failed.

    A HomeAssistantError, so Home Assistant shows the message to the user
    and continue_on_error works, even if a caller does not convert it.
    """


class EnstoNotConnectedError(EnstoBleError):
    """The thermostat is not connected."""


def error_cause(err: BaseException) -> str:
    """Return the cause of an error for messages.

    TimeoutError has no message, so the type name is used instead.

    Args:
        err: The original error.

    Returns:
        The error message, or the error type if the message is empty.
    """
    return str(err) or type(err).__name__
