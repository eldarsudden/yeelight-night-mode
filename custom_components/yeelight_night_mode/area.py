"""Night-mode switches grouping supported Yeelight lights by area."""
from __future__ import annotations

from collections import defaultdict

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .discovery import NightModeTarget


@callback
def async_setup_area_switches(
    hass: HomeAssistant,
    entry: ConfigEntry,
    targets: list[NightModeTarget],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create area groups and keep membership in sync with the registries."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)
    # Registry UUIDs survive entity ID renames. Only discovered, supported
    # lights are eligible; unrelated lights in the same area are excluded.
    sources = []
    for target in targets:
        light = (
            entity_registry.async_get(target.light_entity_id)
            if target.light_entity_id
            else None
        )
        sensor = entity_registry.async_get(target.night_sensor_entity_id)
        if light is not None and sensor is not None:
            sources.append((light.id, sensor.id))

    groups: dict[str, YeelightAreaNightModeSwitch] = {}
    source_entity_ids: set[str] = set()

    @callback
    def async_refresh(event: Event | None = None) -> None:
        if event is not None and event.event_type == er.EVENT_ENTITY_REGISTRY_UPDATED:
            changed_id = event.data["entity_id"]
            changed = entity_registry.async_get(changed_id)
            if changed_id not in source_entity_ids and (
                changed is None or changed.id not in source_registry_ids
            ):
                return

        members: dict[str, list[tuple[str, str]]] = defaultdict(list)
        source_entity_ids.clear()
        for light_id, sensor_id in sources:
            light = entity_registry.async_get(light_id)
            sensor = entity_registry.async_get(sensor_id)
            if light is None or sensor is None:
                continue
            source_entity_ids.update((light.entity_id, sensor.entity_id))
            if light.disabled_by is not None or sensor.disabled_by is not None:
                continue
            device = device_registry.async_get(light.device_id) if light.device_id else None
            area_id = light.area_id or (device.area_id if device else None)
            if area_id and area_registry.async_get_area(area_id) is not None:
                members[area_id].append((light.entity_id, sensor.entity_id))

        new_groups = []
        for area_id in members.keys() | groups.keys():
            area = area_registry.async_get_area(area_id)
            if area_id not in groups:
                groups[area_id] = YeelightAreaNightModeSwitch(area_id)
                new_groups.append(groups[area_id])
            # Retain empty groups as unavailable so their entity IDs and user
            # customizations survive moving the last bulb out and back again.
            groups[area_id].async_set_members(
                area.name if area else area_id, members.get(area_id, [])
            )
        if new_groups:
            async_add_entities(new_groups)

    source_registry_ids = {source_id for pair in sources for source_id in pair}
    for event_type in (
        ar.EVENT_AREA_REGISTRY_UPDATED,
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
        er.EVENT_ENTITY_REGISTRY_UPDATED,
    ):
        entry.async_on_unload(hass.bus.async_listen(event_type, async_refresh))
    async_refresh()


class YeelightAreaNightModeSwitch(SwitchEntity):
    """Control night mode for the supported Yeelight lights in one area."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "area_night_mode"
    _attr_icon = "mdi:weather-night"
    _attr_is_on = False
    _attr_available = False

    def __init__(self, area_id: str) -> None:
        self._area_id = area_id
        self._attr_unique_id = f"{DOMAIN}_area_{area_id}_night_mode"
        self._members: list[tuple[str, str]] = []
        self._unsubscribe_states = None
        self._added = False

    @property
    def suggested_object_id(self) -> str:
        return f"yeelight_{self._area_id}_night_mode"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "area_id": self._area_id,
            "entity_id": [light_id for light_id, _ in self._members],
        }

    @callback
    def async_set_members(self, area_name: str, members: list[tuple[str, str]]) -> None:
        """Update the name, membership and state subscriptions."""
        self._attr_translation_placeholders = {"area": area_name}
        self.__dict__.pop("name", None)
        changed = self._members != members
        self._members = members
        if self._added:
            if changed:
                self._async_subscribe()
            self._async_update_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        if self.registry_entry is not None and self.registry_entry.area_id != self._area_id:
            registry.async_update_entity(self.entity_id, area_id=self._area_id)
        self._added = True
        self.async_on_remove(self._async_unsubscribe)
        self._async_subscribe()
        self._async_update_state()

    @callback
    def _async_unsubscribe(self) -> None:
        self._added = False
        if self._unsubscribe_states is not None:
            self._unsubscribe_states()
            self._unsubscribe_states = None

    @callback
    def _async_subscribe(self) -> None:
        if self._unsubscribe_states is not None:
            self._unsubscribe_states()
            self._unsubscribe_states = None
        if self._members:
            self._unsubscribe_states = async_track_state_change_event(
                self.hass,
                {entity_id for pair in self._members for entity_id in pair},
                self._async_update_state,
            )

    def _available_members(self) -> list[tuple[str, str]]:
        available = []
        for light_id, sensor_id in self._members:
            light = self.hass.states.get(light_id)
            sensor = self.hass.states.get(sensor_id)
            if (
                light is not None
                and light.state in (STATE_ON, STATE_OFF)
                and sensor is not None
                and sensor.state in (STATE_ON, STATE_OFF)
            ):
                available.append((light_id, sensor.state))
        return available

    @callback
    def _async_update_state(self, event: Event | None = None) -> None:
        members = self._available_members()
        self._attr_available = bool(members)
        self._attr_is_on = any(state == STATE_ON for _, state in members)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_mode("moonlight")

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_mode("normal")

    async def _async_set_mode(self, mode: str) -> None:
        light_ids = [light_id for light_id, _ in self._available_members()]
        # Never send an empty target, which can mean "all entities" to a service.
        if light_ids:
            await self.hass.services.async_call(
                "yeelight",
                "set_mode",
                {"mode": mode},
                target={"entity_id": light_ids},
                blocking=True,
                context=self._context,
            )
