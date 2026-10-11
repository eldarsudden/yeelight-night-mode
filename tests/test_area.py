"""Behavior tests using an in-memory Home Assistant API stand-in.

Run with: python3 -m unittest discover -s tests -v
These tests need no running Home Assistant or Yeelight hardware.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch


class FakeSwitch:
    hass = None
    registry_entry = None
    _context = None

    async def async_added_to_hass(self):
        pass

    def async_on_remove(self, unsubscribe):
        self.on_remove = unsubscribe

    def async_write_ha_state(self):
        self.writes = getattr(self, "writes", 0) + 1

    @property
    def available(self):
        return self._attr_available

    @property
    def is_on(self):
        return self._attr_is_on


class Registry:
    def __init__(self):
        self.entries = {}

    def add(self, entity_id, *, area_id=None, device_id=None, disabled_by=None):
        entry = SimpleNamespace(
            id=f"uuid-{entity_id}", entity_id=entity_id, area_id=area_id,
            device_id=device_id, disabled_by=disabled_by,
        )
        self.entries[entry.id] = entry
        return entry

    def async_get(self, key):
        return next(
            (entry for entry in self.entries.values()
             if key in (entry.id, entry.entity_id)), None
        )

    def async_update_entity(self, entity_id, **changes):
        entry = self.async_get(entity_id)
        for key, value in changes.items():
            setattr(entry, "entity_id" if key == "new_entity_id" else key, value)
        return entry


class Bus:
    def __init__(self):
        self.listeners = {}

    def async_listen(self, event_type, callback):
        listeners = self.listeners.setdefault(event_type, [])
        listeners.append(callback)
        return lambda: listeners.remove(callback)

    def fire(self, event_type, **data):
        event = SimpleNamespace(event_type=event_type, data=data)
        for callback in tuple(self.listeners.get(event_type, [])):
            callback(event)


class States:
    def __init__(self):
        self.states = {}
        self.listeners = []

    def get(self, entity_id):
        return self.states.get(entity_id)

    def set(self, entity_id, state):
        self.states[entity_id] = SimpleNamespace(state=state)
        for entity_ids, callback in tuple(self.listeners):
            if entity_id in entity_ids:
                callback(SimpleNamespace(data={}))

    def track(self, entity_ids, callback):
        listener = (set(entity_ids), callback)
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)


class Entry:
    entry_id = "night-mode-entry"

    def __init__(self, entity_type="switch"):
        self.data = {"entity_type": entity_type}
        self.options = {}
        self.unload_callbacks = []

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)

    def add_update_listener(self, callback):
        return lambda: None


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


class AreaSwitchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entities = Registry()
        self.devices = {}
        self.areas = {
            "bedroom": SimpleNamespace(name="Спальня"),
            "kitchen": SimpleNamespace(name="Кухня"),
        }
        self.hass = SimpleNamespace(
            data={}, bus=Bus(), states=States(),
            services=SimpleNamespace(async_call=AsyncMock()),
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
            ),
        )
        fake_modules = {
            "homeassistant": module("homeassistant"),
            "homeassistant.components": module("components"),
            "homeassistant.components.switch": module("switch", SwitchEntity=FakeSwitch),
            "homeassistant.config_entries": module("config_entries", ConfigEntry=Entry),
            "homeassistant.const": module("const", STATE_ON="on", STATE_OFF="off"),
            "homeassistant.core": module(
                "core", HomeAssistant=object, Event=object,
                EventStateChangedData=dict, callback=lambda function: function,
            ),
            "homeassistant.helpers": module("helpers"),
            "homeassistant.helpers.entity_platform": module("entity_platform", AddEntitiesCallback=object),
            "homeassistant.helpers.entity_registry": module(
                "entity_registry", async_get=lambda hass: self.entities,
                EVENT_ENTITY_REGISTRY_UPDATED="entity_registry_updated",
            ),
            "homeassistant.helpers.device_registry": module(
                "device_registry", async_get=lambda hass: SimpleNamespace(async_get=self.devices.get),
                EVENT_DEVICE_REGISTRY_UPDATED="device_registry_updated",
            ),
            "homeassistant.helpers.area_registry": module(
                "area_registry", async_get=lambda hass: SimpleNamespace(async_get_area=self.areas.get),
                EVENT_AREA_REGISTRY_UPDATED="area_registry_updated",
            ),
            "homeassistant.helpers.event": module(
                "event", async_track_state_change_event=lambda hass, ids, callback: hass.states.track(ids, callback),
            ),
            "yeelight": module("yeelight"),
        }
        for name, child in fake_modules.items():
            parent, _, attribute = name.rpartition(".")
            if parent in fake_modules:
                setattr(fake_modules[parent], attribute, child)
        self.modules_patch = patch.dict(sys.modules, fake_modules)
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        package = "custom_components.yeelight_night_mode"
        self.integration = importlib.import_module(package)
        self.area = importlib.import_module(f"{package}.area")
        self.switch = importlib.import_module(f"{package}.switch")
        self.discovery = importlib.import_module(f"{package}.discovery")
        self.entry = Entry()
        self.groups = []

    def add_bulb(self, name, area_id="bedroom", sensor_state="off", light_state="on"):
        light_id, sensor_id = f"light.{name}", f"binary_sensor.{name}_night"
        self.devices[name] = SimpleNamespace(area_id=area_id)
        self.entities.add(light_id, device_id=name)
        self.entities.add(sensor_id, device_id=name)
        self.hass.states.set(light_id, light_state)
        self.hass.states.set(sensor_id, sensor_state)
        return self.discovery.NightModeTarget(
            name, name, name, name, light_id, sensor_id, name,
        )

    async def setup_groups(self, targets):
        self.area.async_setup_area_switches(
            self.hass, self.entry, targets, self.groups.extend,
        )
        await self.add_pending_groups()

    async def add_pending_groups(self):
        for group in self.groups:
            if group.hass is not None:
                continue
            group.hass = self.hass
            group.entity_id = f"switch.{group.suggested_object_id}"
            group.registry_entry = self.entities.add(group.entity_id)
            await group.async_added_to_hass()

    def group(self, area_id):
        return next(group for group in self.groups if group.extra_state_attributes["area_id"] == area_id)

    async def test_one_switch_per_area_and_exact_service_targets(self):
        targets = [self.add_bulb("a"), self.add_bulb("b"), self.add_bulb("c", "kitchen")]
        self.add_bulb("unsupported")  # Not discovered as night-mode capable.
        await self.setup_groups(targets)
        self.assertEqual(len(self.groups), 2)
        group = self.group("bedroom")
        self.assertEqual(group.entity_id, "switch.yeelight_bedroom_night_mode")
        self.assertEqual(group.registry_entry.area_id, "bedroom")
        group._context = "test-context"
        for action, mode in ((group.async_turn_on, "moonlight"), (group.async_turn_off, "normal")):
            await action()
            self.hass.services.async_call.assert_awaited_with(
                "yeelight", "set_mode", {"mode": mode},
                target={"entity_id": ["light.a", "light.b"]},
                blocking=True, context="test-context",
            )

    async def test_state_follows_sensors_and_any_member_on(self):
        await self.setup_groups([self.add_bulb("a"), self.add_bulb("b")])
        group = self.group("bedroom")
        self.assertTrue(group.available)
        self.assertFalse(group.is_on)
        self.hass.states.set("binary_sensor.b_night", "on")
        self.assertTrue(group.is_on)
        self.hass.states.set("binary_sensor.b_night", "off")
        self.assertFalse(group.is_on)
        await group.async_turn_on()
        self.assertFalse(group.is_on)  # Authoritative state is still off.

    async def test_unavailable_unknown_missing_and_empty_targets(self):
        await self.setup_groups([
            self.add_bulb("a", sensor_state="on"),
            self.add_bulb("b", sensor_state="unknown"),
            self.add_bulb("c", sensor_state="on", light_state="unavailable"),
        ])
        group = self.group("bedroom")
        await group.async_turn_on()
        self.assertEqual(self.hass.services.async_call.call_args.kwargs["target"], {"entity_id": ["light.a"]})
        self.hass.states.set("light.a", "unavailable")
        self.assertFalse(group.available)
        self.hass.services.async_call.reset_mock()
        await group.async_turn_on()
        await group.async_turn_off()
        self.hass.services.async_call.assert_not_awaited()
        self.hass.states.set("light.a", "off")
        self.assertTrue(group.available)
        self.hass.states.states.pop("binary_sensor.a_night")
        self.hass.states.set("light.a", "on")
        self.assertFalse(group.available)

    async def test_entity_area_override_and_unassigned_bulbs(self):
        targets = [self.add_bulb("a"), self.add_bulb("b", None)]
        self.entities.async_get("light.a").area_id = "kitchen"
        await self.setup_groups(targets)
        self.assertEqual(len(self.groups), 1)
        self.assertEqual(self.group("kitchen").extra_state_attributes["entity_id"], ["light.a"])

    async def test_move_rename_and_return_preserve_group_identity(self):
        await self.setup_groups([self.add_bulb("a", sensor_state="on")])
        bedroom = self.group("bedroom")
        self.devices["a"].area_id = "kitchen"
        self.hass.bus.fire("device_registry_updated", device_id="a")
        await self.add_pending_groups()
        self.assertFalse(bedroom.available)
        self.assertTrue(self.group("kitchen").is_on)
        self.areas["kitchen"].name = "Новая кухня"
        self.hass.bus.fire("area_registry_updated", area_id="kitchen")
        self.assertEqual(self.group("kitchen")._attr_translation_placeholders, {"area": "Новая кухня"})
        self.devices["a"].area_id = "bedroom"
        self.hass.bus.fire("device_registry_updated", device_id="a")
        self.assertIs(bedroom, self.group("bedroom"))
        self.assertTrue(bedroom.available)
        self.assertFalse(self.group("kitchen").available)

    async def test_source_entity_id_renames_update_members_and_listeners(self):
        await self.setup_groups([self.add_bulb("a")])
        for old, new in (("light.a", "light.renamed"), ("binary_sensor.a_night", "binary_sensor.renamed")):
            self.entities.async_update_entity(old, new_entity_id=new)
            self.hass.states.set(new, "on")
            self.hass.bus.fire("entity_registry_updated", entity_id=new, changes={"entity_id": old})
        group = self.group("bedroom")
        self.assertEqual(group.extra_state_attributes["entity_id"], ["light.renamed"])
        self.assertTrue(group.is_on)
        self.hass.states.set("binary_sensor.renamed", "off")
        self.assertFalse(group.is_on)
        self.assertEqual(len(self.hass.states.listeners), 1)

    async def test_disabled_or_removed_sources_leave_no_controllable_targets(self):
        await self.setup_groups([self.add_bulb("a")])
        light = self.entities.async_get("light.a")
        light.disabled_by = "user"
        self.hass.bus.fire("entity_registry_updated", entity_id="light.a")
        group = self.group("bedroom")
        self.assertFalse(group.available)
        light.disabled_by = None
        self.hass.bus.fire("entity_registry_updated", entity_id="light.a")
        self.assertTrue(group.available)
        del self.entities.entries[light.id]
        self.hass.bus.fire("entity_registry_updated", entity_id="light.a", action="remove")
        self.assertFalse(group.available)
        await group.async_turn_on()
        self.hass.services.async_call.assert_not_awaited()

    async def test_no_groups_without_eligible_sources(self):
        await self.setup_groups([self.add_bulb("a", None)])
        self.assertEqual(self.groups, [])

    async def test_unload_removes_registry_and_state_listeners(self):
        await self.setup_groups([self.add_bulb("a")])
        for callback in self.entry.unload_callbacks:
            callback()
        for group in self.groups:
            group.on_remove()
        self.assertFalse(any(self.hass.bus.listeners.values()))
        self.assertEqual(self.hass.states.listeners, [])

    async def test_both_entity_types_load_area_switches(self):
        target = self.add_bulb("a")
        for entity_type, expected in (("switch", ["switch"]), ("light", ["switch", "light"])):
            with self.subTest(entity_type=entity_type):
                entry = Entry(entity_type)
                await self.integration.async_setup_entry(self.hass, entry)
                self.hass.config_entries.async_forward_entry_setups.assert_awaited_with(entry, expected)
                entities = []
                with patch.object(self.switch, "async_discover_targets", AsyncMock(return_value=[target])):
                    await self.switch.async_setup_entry(self.hass, entry, entities.extend)
                area_switches = [entity for entity in entities if isinstance(entity, self.area.YeelightAreaNightModeSwitch)]
                individual_switches = [entity for entity in entities if isinstance(entity, self.switch.YeelightNightModeSwitch)]
                self.assertEqual(len(area_switches), 1)
                self.assertEqual(len(individual_switches), int(entity_type == "switch"))
                entry.options = {"entity_type": "light" if entity_type == "switch" else "switch"}
                await self.integration.async_unload_entry(self.hass, entry)
                self.hass.config_entries.async_unload_platforms.assert_awaited_with(entry, expected)


if __name__ == "__main__":
    unittest.main()
