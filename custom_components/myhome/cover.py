"""Support for MyHome covers."""
from homeassistant.components.cover import (
    ATTR_POSITION,
    DOMAIN as PLATFORM,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from homeassistant.helpers.event import async_track_point_in_time

from OWNd.message import (
    OWNAutomationEvent,
    OWNAutomationCommand,
)

from datetime import datetime, timedelta

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_ENTITY_NAME,
    CONF_WHO,
    CONF_WHERE,
    CONF_BUS_INTERFACE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_ADVANCED_SHUTTER,
    CONF_DURATION,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _covers = []
    _configured_covers = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _cover in _configured_covers.keys():
        _cover = MyHOMECover(
            hass=hass,
            device_id=_cover,
            who=_configured_covers[_cover][CONF_WHO],
            where=_configured_covers[_cover][CONF_WHERE],
            interface=_configured_covers[_cover][CONF_BUS_INTERFACE] if CONF_BUS_INTERFACE in _configured_covers[_cover] else None,
            name=_configured_covers[_cover][CONF_NAME],
            entity_name=_configured_covers[_cover][CONF_ENTITY_NAME],
            advanced=_configured_covers[_cover][CONF_ADVANCED_SHUTTER],
            manufacturer=_configured_covers[_cover][CONF_MANUFACTURER],
            model=_configured_covers[_cover][CONF_DEVICE_MODEL],
            gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            duration=_configured_covers[_cover][CONF_DURATION],
        )
        _covers.append(_cover)

    async_add_entities(_covers)


async def async_unload_entry(hass, config_entry):  # pylint: disable=unused-argument
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_covers = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _cover in _configured_covers.keys():
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_cover]


class MyHOMECover(MyHOMEEntity, CoverEntity):
    device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        device_id: str,
        who: str,
        where: str,
        interface: str,
        advanced: bool,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
        duration: int
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._attr_name = entity_name

        self.duration = timedelta(seconds=duration) if duration is not None else None
        self.guest_position = duration is not None
        self._attr_current_cover_position = 0
        self._last_date = None
        self.cancel = None

        self._interface = interface
        if(self.isZigbee()):
            self._full_where = f"{self._where}{self._interface}"
        else:
            self._full_where = f"{self._where}#4#{self._interface}" if self._interface is not None else self._where

        self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if advanced:
            self._attr_supported_features |= CoverEntityFeature.SET_POSITION
        self._gateway_handler = gateway

        if(self.isZigbee()):
            id = int(where[:len(where) -2])
            unit = int(where[len(where) -1:])
            self._attr_extra_state_attributes = {
                "ID":   f'0x{id:0>8X}',
                "Unit": f'{unit:02d}'
            }
        else:
            self._attr_extra_state_attributes = {
                "A": where[: len(where) // 2],
                "PL": where[len(where) // 2 :],
            }
        
        if self._interface is not None:
            if self.isZigbee():
                self._attr_extra_state_attributes["Int"] = "Zigbee"
            else:
                self._attr_extra_state_attributes["Int"] = self._interface
        if self.duration is not None:
            self._attr_extra_state_attributes["Duration"] = self.duration.total_seconds()

        self._attr_current_cover_position = None
        self._attr_is_opening = None
        self._attr_is_closing = None
        self._attr_is_closed = None

    def isZigbee(self):
        return self._interface is not None and self._interface == "#9"
    
    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(OWNAutomationCommand.status(self._full_where))

    async def async_open_cover(self, **kwargs):  # pylint: disable=unused-argument
        """Open the cover."""
        await self._gateway_handler.send(OWNAutomationCommand.raise_shutter(self._full_where))

    async def async_close_cover(self, **kwargs):  # pylint: disable=unused-argument
        """Close cover."""
        await self._gateway_handler.send(OWNAutomationCommand.lower_shutter(self._full_where))

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        if ATTR_POSITION in kwargs:
            position = kwargs[ATTR_POSITION]
            await self._gateway_handler.send(OWNAutomationCommand.set_shutter_level(self._full_where, position))

    async def async_stop_cover(self, **kwargs):  # pylint: disable=unused-argument
        """Stop the cover."""
        await self._gateway_handler.send(OWNAutomationCommand.stop_shutter(self._full_where))

    def handle_event(self, message: OWNAutomationEvent):
        """Handle an event message."""
        self.cancel_timer()
        LOGGER.info(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )

        date=datetime.now()
        if message.current_position is not None:
            self._attr_current_cover_position = message.current_position
            # no need to guess position
            self.guest_position = False
        else:
            if(self._last_date is not None):
                delta = date - self._last_date
                percent = int(delta.total_seconds() / self.duration.total_seconds() *100)
                position = self._attr_current_cover_position if self._attr_current_cover_position is not None else 100
                total = position
                if self._attr_is_opening is not None and self._attr_is_opening:
                   total = position + percent
                if self._attr_is_closing is not None and self._attr_is_closing:
                   total = position - percent
                if total > 100:
                    total = 100
                if total < 0:
                    total = 0
                self._attr_current_cover_position = total

        self._attr_is_opening = message.is_opening
        self._attr_is_closing = message.is_closing

        if self.guest_position and (message.is_opening or message.is_closing):
            # TODO compute required duration
            self.cancel= async_track_point_in_time(self.hass, self.async_timeout, date + self.duration)

        if message.is_closed is not None:
            self._attr_is_closed = message.is_closed
        else:
            self._attr_is_closed = True if self._attr_current_cover_position == 0 else False
                
        self._last_date=date
        self.async_schedule_update_ha_state()

    async def async_timeout(self, now):
        """Send stop command if duration expire."""
        self.cancel = None
        await self.async_stop_cover()


    async def async_will_remove_from_hass(self) -> None:
        """Remove scheduled task if any."""
        self.cancel_timer()
        await super().async_will_remove_from_hass()

    def cancel_timer(self):
        if self.cancel is not None:
            self.cancel()
            self.cancel=None