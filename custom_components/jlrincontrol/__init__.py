"""
Jaguar Landrover Component for In Control API

Includes Sensor Devices and Services

https://github.com/msp1974/homeassistant-jlrincontrol.git
msparker@sky.com
"""
import asyncio
import json
import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import jlrpy
import voluptuous as vol
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    LENGTH_KILOMETERS,
    LENGTH_MILES,
    PRESSURE_PSI,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
)
from homeassistant.core import callback
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt

from .const import (
    DOMAIN,
    KMS_TO_MILES,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    DEFAULT_HEATH_UPDATE_INTERVAL,
    SIGNAL_STATE_UPDATED,
    JLR_SERVICES,
)
from .services import JLRService

# from homeassistant.helpers.icon import icon_for_battery_level

_LOGGER = logging.getLogger(__name__)

MIN_UPDATE_INTERVAL = timedelta(minutes=1)
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=5)

ATTR_PIN = "pin"
ATTR_CHARGE_LEVEL = "max_charge_level"
ATTR_TARGET_VALUE = "target_value"
ATTR_TARGET_TEMP = "target_temp"
CONF_DEBUG_DATA = "debug_data"
CONF_DISTANCE_UNIT = "distance_unit"
CONF_HEALTH_UPDATE_INTERVAL = "health_update_interval"

PLATFORMS = ["sensor", "lock", "device_tracker"]


SERVICES_BASE_SCHEMA = {
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
}
SERVICES_PIN_SCHEMA = {
    vol.Required(ATTR_PIN): vol.Coerce(str),
}
SERVICES_TARGET_TEMP_SCHEMA = {
    vol.Required(ATTR_TARGET_TEMP): vol.Coerce(int),
}
SERVICES_TARGET_VALUE_SCHEMA = {
    vol.Required(ATTR_TARGET_VALUE): vol.Coerce(int),
}
SERVICES_CHARGE_LEVEL_SCHEMA = {
    vol.Required(ATTR_CHARGE_LEVEL): vol.Coerce(int),
}


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_DISTANCE_UNIT): vol.In(
                    [LENGTH_KILOMETERS, LENGTH_MILES]
                ),
                vol.Optional(CONF_DEBUG_DATA, default=False): cv.boolean,
                vol.Optional(CONF_PIN): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): (
                    vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))
                ),
                vol.Optional(
                    CONF_HEALTH_UPDATE_INTERVAL, default=DEFAULT_HEATH_UPDATE_INTERVAL
                ): vol.Coerce(int),
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Setup JLR InConnect component"""
    data = JLRApiHandler(hass, config)

    # Get initial update and schedule interval update
    await data.async_update()

    if not data.vehicle:
        # No vehicles or wrong credentials
        _LOGGER.error("Unable to get vehicles from api.  Check credentials")
        return False

    _LOGGER.debug("Connected to API")
    hass.data[DOMAIN] = data

    for platform in PLATFORMS:
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config))

    async def call_service(service):
        # Get service info
        if JLR_SERVICES[service.service]:
            _LOGGER.debug(
                "Service - {}, Data - {}".format(service.service, service.data)
            )
            kwargs = {}
            kwargs["service_name"] = JLR_SERVICES[service.service].get("function_name")
            kwargs["service_code"] = JLR_SERVICES[service.service].get("service_code")
            for k, v in service.data.items():
                kwargs[k] = v

            jlr_service = JLRService(hass, data)
            await jlr_service.async_call_service(**kwargs)

    def get_schema(schema_list):
        s = {}
        for schema in schema_list:
            s.update(eval(schema))
        return vol.Schema(s)

    # Add services
    for service, service_info in JLR_SERVICES.items():
        # TODO: Only add services supported by vehicle
        _LOGGER.debug("Adding {} service".format(service))
        hass.services.async_register(
            DOMAIN,
            service,
            call_service,
            schema=get_schema(service_info.get("schema")),
        )

    return True


class JLRApiHandler:
    def __init__(self, hass, config):
        self._hass = hass
        self.config = config
        self.vehicle = None
        self.connection = None
        self.attributes = None
        self.status = None
        self.wakeup = None
        self.position = None
        self.user_info = None
        self.timer_handle = None
        self.health_timer_handle = None
        self.pin = self.config[DOMAIN].get(CONF_PIN)
        self.update_interval = self.config[DOMAIN].get(CONF_SCAN_INTERVAL) * 60
        self.health_update_interval = (
            self.config[DOMAIN].get(CONF_HEALTH_UPDATE_INTERVAL) * 60
        )

        _LOGGER.debug("Creating connection to JLR InControl API")
        self.connection = jlrpy.Connection(
            email=self.config[DOMAIN].get(CONF_USERNAME),
            password=self.config[DOMAIN].get(CONF_PASSWORD),
        )

        # Get one time info
        self.vehicle = self.connection.vehicles[0]
        self.attributes = self.vehicle.get_attributes()

        # Add one time dump of attr and status data for debugging
        if self.config[DOMAIN].get(CONF_DEBUG_DATA):
            _LOGGER.debug("ATTRIBUTE DATA - {}".format(self.attributes))
            status = self.vehicle.get_status()
            self.status = {d["key"]: d["value"] for d in status["vehicleStatus"]}
            _LOGGER.debug("STATUS DATA - {}".format(self.status))

        # Schedule health update and repeat interval
        if self.health_update_interval > 0:
            _LOGGER.debug(
                "Scheduling vehicle health update on {} minute interval".format(
                    int(self.health_update_interval / 60)
                )
            )
            self.do_health_update()
        else:
            _LOGGER.debug(
                "Scheduled vehicle health update is disabled.  Add to configuration.yaml to enable."
            )

        _LOGGER.debug(
            "Scheduling update from InControl servers on {} minute interval".format(
                int(self.update_interval / 60)
            )
        )

    @callback
    def do_status_update(self):
        self._hass.async_create_task(self.async_update())

    @callback
    def do_health_update(self):
        self._hass.async_create_task(self.async_health_update())

    async def async_update(self):
        # Cancel any scheduled timer if this has been forced
        if self.timer_handle:
            self.timer_handle.cancel()

        self.position = self.vehicle.get_position()
        status = self.vehicle.get_status()
        self.status = {d["key"]: d["value"] for d in status["vehicleStatus"]}
        self.status["lastUpdatedTime"] = status.get("lastUpdatedTime")

        # Wakeup may not be available on all models - issue #1
        try:
            self.wakeup = self.vehicle.get_wakeup_time()
        except Exception:
            self.wakeup = None

        # Schedule next update
        self.timer_handle = self._hass.loop.call_later(
            self.update_interval, self.do_status_update
        )

        _LOGGER.info("JLR InControl Update Received")
        # Send update notice to all components to update
        async_dispatcher_send(self._hass, SIGNAL_STATE_UPDATED)

        return True

    async def async_health_update(self):
        # Cancel any scheduled timer if this has been forced
        if self.health_timer_handle:
            self.health_timer_handle.cancel()

        _LOGGER.info("Requesting scheduled health status update")

        service = JLR_SERVICES["update_health_status"]
        kwargs = {}
        kwargs["service_name"] = service.get("function_name")
        kwargs["service_code"] = service.get("service_code")
        jlr_service = JLRService(self._hass, self._hass.data[DOMAIN])
        await jlr_service.async_call_service(**kwargs)

        # Schedule next update
        self.health_timer_handle = self._hass.loop.call_later(
            self.health_update_interval, self.do_health_update
        )

        # Call sensor data update
        await self.async_update()

        return True

    async def async_update_vehicle_health(self):
        # TODO: Add checking that it has been successful
        # by calling service status
        await self.vehicle.get_health_status()

    def get_distance_units(self):
        if self.config[DOMAIN].get(CONF_DISTANCE_UNIT):
            return self.config[DOMAIN].get(CONF_DISTANCE_UNIT)
        else:
            return self._hass.config.units.length_unit

    def get_odometer(self):
        self.units = self.get_distance_units()
        if self.units == LENGTH_KILOMETERS:
            return int(int(self.status.get("ODOMETER_METER")) / 1000)
        else:
            return int(self.status.get("ODOMETER_MILES"))


class JLREntity(Entity):
    def __init__(self, data, sensor_type):
        """Create a new generic Dyson sensor."""
        self._name = None
        self._data = data
        self._sensor_type = sensor_type
        self._icon = "mid:cloud"
        self._entity_prefix = (
            self._data.attributes.get("vehicleBrand")
            + self._data.attributes.get("vehicleType")
            + "-"
            + self._data.vehicle.vin[-6:]
        )

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        """Return the icon for this sensor."""
        return self._icon

    @property
    def unique_id(self):
        """Return the sensor's unique id."""
        return f"{self._entity_prefix}-{self._sensor_type}"

    async def async_update(self):
        _LOGGER.debug("Updating {}".format(self._name))
        return True

    async def async_added_to_hass(self):
        """Subscribe for update from the hub"""

        async def async_update_state():
            """Update sensor state."""
            await self.async_update_ha_state(True)

        async_dispatcher_connect(self.hass, SIGNAL_STATE_UPDATED, async_update_state)

    def to_local_datetime(self, datetime: str):
        try:
            return dt.as_local(dt.parse_datetime(datetime))
        except Exception:
            return None
