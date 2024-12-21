"""Support for MyHome lights."""
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_FLASH,
    FLASH_LONG,
    FLASH_SHORT,
    ATTR_TRANSITION,
    DOMAIN as PLATFORM,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from OWNd.message import (
    OWNLightingEvent,
    OWNLightingCommand,
)

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_ENTITY_NAME,
    CONF_ICON,
    CONF_ICON_ON,
    CONF_WHO,
    CONF_WHERE,
    CONF_BUS_INTERFACE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_DIMMABLE,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _lights = []
    _configured_lights = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _light in _configured_lights.keys():
        _light = MyHOMELight(
            hass=hass,
            device_id=_light,
            who=_configured_lights[_light][CONF_WHO],
            where=_configured_lights[_light][CONF_WHERE],
            icon=_configured_lights[_light][CONF_ICON],
            icon_on=_configured_lights[_light][CONF_ICON_ON],
            interface=_configured_lights[_light][CONF_BUS_INTERFACE] if CONF_BUS_INTERFACE in _configured_lights[_light] else None,
            name=_configured_lights[_light][CONF_NAME],
            entity_name=_configured_lights[_light][CONF_ENTITY_NAME],
            dimmable=_configured_lights[_light][CONF_DIMMABLE],
            manufacturer=_configured_lights[_light][CONF_MANUFACTURER],
            model=_configured_lights[_light][CONF_DEVICE_MODEL],
            gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
        )
        _lights.append(_light)

    async_add_entities(_lights)


async def async_unload_entry(hass, config_entry):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_lights = hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM]

    for _light in _configured_lights.keys():
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][_light]


def eight_bits_to_percent(value: int) -> int:
    return int(round(100 / 255 * value, 0))


def percent_to_eight_bits(value: int) -> int:
    return int(round(255 / 100 * value, 0))


class MyHOMELight(MyHOMEEntity, LightEntity):
    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        icon: str,
        icon_on: str,
        device_id: str,
        who: str,
        where: str,
        interface: str,
        dimmable: bool,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
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

        self._interface = interface
        if(self.isZigbee()):
            self._full_where = f"{self._where}{self._interface}"
        else:
            self._full_where = f"{self._where}#4#{self._interface}" if self._interface is not None else self._where

        self._attr_supported_features = 0
        self._attr_supported_color_modes: set[ColorMode] = set()

        if dimmable:
            self._attr_supported_color_modes.add(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_features |= LightEntityFeature.TRANSITION
        else:
            self._attr_supported_color_modes.add(ColorMode.ONOFF)
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_features |= LightEntityFeature.FLASH

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

        self._on_icon = icon_on
        self._off_icon = icon

        if self._off_icon is not None:
            self._attr_icon = self._off_icon

        self._attr_is_on = None
        self._attr_brightness = None
        self._attr_brightness_pct = None

    def isZigbee(self):
        return self._interface is not None and self._interface == "#9"
    
    def needUpdate(self, message: OWNLightingEvent):
        return self.isZigbee() and ColorMode.BRIGHTNESS in self._attr_supported_color_modes and message.is_on and message._brightness_preset is None and self._attr_brightness is None

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        if ColorMode.BRIGHTNESS in self._attr_supported_color_modes and not self.isZigbee():
            await self._gateway_handler.send_status_request(OWNLightingCommand.get_brightness(self._full_where))
        else:
            if self._attr_is_on is None or self._attr_is_on:
                await self._gateway_handler.send_status_request(OWNLightingCommand.status(self._full_where))

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""

        if ATTR_FLASH in kwargs and self._attr_supported_features & LightEntityFeature.FLASH:
            if kwargs[ATTR_FLASH] == FLASH_SHORT:
                return await self._gateway_handler.send(OWNLightingCommand.flash(self._full_where, 0.5))
            elif kwargs[ATTR_FLASH] == FLASH_LONG:
                return await self._gateway_handler.send(OWNLightingCommand.flash(self._full_where, 1.5))

        if ((ATTR_BRIGHTNESS in kwargs or ATTR_BRIGHTNESS_PCT in kwargs) and ColorMode.BRIGHTNESS in self._attr_supported_color_modes) or (
            ATTR_TRANSITION in kwargs and self._attr_supported_features & LightEntityFeature.TRANSITION
        ):
            if ATTR_BRIGHTNESS in kwargs or ATTR_BRIGHTNESS_PCT in kwargs:
                _percent_brightness = eight_bits_to_percent(kwargs[ATTR_BRIGHTNESS]) if ATTR_BRIGHTNESS in kwargs else None
                _percent_brightness = kwargs[ATTR_BRIGHTNESS_PCT] if ATTR_BRIGHTNESS_PCT in kwargs else _percent_brightness
                if _percent_brightness == 0:
                    return await self.async_turn_off(**kwargs)
                else:
                    self._attr_brightness_pct = (_percent_brightness +4) // 10
                    if self._attr_brightness_pct < 2:
                        self._attr_brightness_pct = 2
                    self._attr_brightness_pct = self._attr_brightness_pct * 10
                    self._attr_brightness = percent_to_eight_bits(self._attr_brightness_pct)
                    return (
                        await self._gateway_handler.send(
                            OWNLightingCommand.set_brightness(
                                self._full_where,
                                _percent_brightness,
                                int(kwargs[ATTR_TRANSITION],
                                self.isZigbee())
                            )
                        )
                        if ATTR_TRANSITION in kwargs
                        else await self._gateway_handler.send(OWNLightingCommand.set_brightness(self._full_where, _percent_brightness, 0, self.isZigbee()))
                    )
            else:
                return await self._gateway_handler.send(OWNLightingCommand.switch_on(self._full_where, int(kwargs[ATTR_TRANSITION])))
        else:
            await self._gateway_handler.send(OWNLightingCommand.switch_on(self._full_where))
            if ColorMode.BRIGHTNESS in self._attr_supported_color_modes and not self.isZigbee():
                await self.async_update()

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""

        if ATTR_TRANSITION in kwargs and self._attr_supported_features & LightEntityFeature.TRANSITION:
            return await self._gateway_handler.send(OWNLightingCommand.switch_off(self._full_where, int(kwargs[ATTR_TRANSITION])))

        if ATTR_FLASH in kwargs and self._attr_supported_features & LightEntityFeature.FLASH:
            if kwargs[ATTR_FLASH] == FLASH_SHORT:
                return await self._gateway_handler.send(OWNLightingCommand.flash(self._full_where, 0.5))
            elif kwargs[ATTR_FLASH] == FLASH_LONG:
                return await self._gateway_handler.send(OWNLightingCommand.flash(self._full_where, 1.5))

        return await self._gateway_handler.send(OWNLightingCommand.switch_off(self._full_where))

    def handle_event(self, message: OWNLightingEvent):
        """Handle an event message."""
        LOGGER.info(
            "%s %s",
            self._gateway_handler.log_id,
            message.human_readable_log,
        )
        self._attr_is_on = message.is_on
        if ColorMode.BRIGHTNESS in self._attr_supported_color_modes and message.brightness is not None:
            self._attr_brightness_pct = message.brightness
            self._attr_brightness = percent_to_eight_bits(message.brightness)

        if self.isZigbee() and ColorMode.BRIGHTNESS in self._attr_supported_color_modes:
            if message._brightness_preset is not None:
                self._attr_brightness_pct = message._brightness_preset * 10
                self._attr_brightness = percent_to_eight_bits(self._attr_brightness_pct)

        if self._off_icon is not None and self._on_icon is not None:
            self._attr_icon = self._on_icon if self._attr_is_on else self._off_icon

        self.async_schedule_update_ha_state()
