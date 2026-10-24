"""Options-flow regression tests using a minimal Home Assistant API stand-in."""
from __future__ import annotations

import importlib
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch, sentinel


class FakeFlow:
    def __init_subclass__(cls, *, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


class FakeOptionsFlow(FakeFlow):
    @property
    def config_entry(self):
        """Home Assistant supplies this read-only property after construction."""
        return self.hass.config_entries.async_get_entry(self.handler)


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


class OptionsFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fake_modules = {
            "voluptuous": module("voluptuous"),
            "homeassistant": module("homeassistant"),
            "homeassistant.config_entries": module(
                "config_entries", ConfigEntry=object,
                ConfigFlow=FakeFlow, OptionsFlow=FakeOptionsFlow,
            ),
            "homeassistant.core": module(
                "core", HomeAssistant=object, callback=lambda function: function,
            ),
            "homeassistant.data_entry_flow": module("data_entry_flow", FlowResult=dict),
            "homeassistant.helpers": module("helpers"),
            "homeassistant.helpers.selector": module("selector"),
        }
        for name, child in fake_modules.items():
            parent, _, attribute = name.rpartition(".")
            if parent in fake_modules:
                setattr(fake_modules[parent], attribute, child)
        modules_patch = patch.dict(sys.modules, fake_modules)
        modules_patch.start()
        self.addCleanup(modules_patch.stop)
        self.config_flow = importlib.import_module(
            "custom_components.yeelight_night_mode.config_flow"
        )
        # Schema serialization is outside these lifecycle regression tests.
        schema_patch = patch.object(self.config_flow, "_schema", return_value=sentinel.schema)
        self.schema = schema_patch.start()
        self.addCleanup(schema_patch.stop)
        self.entry = SimpleNamespace(entry_id="night-mode-entry", data={}, options={})

    def create_flow(self):
        # The factory runs before Home Assistant attaches hass and the entry ID.
        flow = self.config_flow.YeelightNightModeConfigFlow.async_get_options_flow(self.entry)
        flow.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_get_entry=Mock(return_value=self.entry))
        )
        flow.handler = self.entry.entry_id
        return flow

    async def test_open_options_with_read_only_config_entry(self):
        flow = self.create_flow()
        result = await flow.async_step_init()
        self.assertEqual(result, {
            "type": "form", "step_id": "init",
            "data_schema": sentinel.schema, "errors": {},
        })
        self.schema.assert_called_once_with("switch", "night_sensor", "", "default", "")

    async def test_open_options_uses_original_setup_data(self):
        self.entry.data = {
            "entity_type": "light", "entity_name_mode": "custom",
            "custom_entity_name": "<light_entity_id>_night",
            "entity_display_name_mode": "custom", "custom_entity_display_name": "Moon",
        }
        await self.create_flow().async_step_init()
        self.schema.assert_called_once_with(
            "light", "custom", "<light_entity_id>_night", "custom", "Moon",
        )

    async def test_saved_options_override_original_setup_data(self):
        self.entry.data = {
            "entity_type": "switch", "entity_name_mode": "night_sensor",
            "custom_entity_name": "old_id", "entity_display_name_mode": "default",
            "custom_entity_display_name": "Old name",
        }
        self.entry.options = {
            "entity_type": "light", "entity_name_mode": "custom",
            "custom_entity_name": "<binary_sensor_id>_moon",
            "entity_display_name_mode": "custom", "custom_entity_display_name": "Moon",
        }
        await self.create_flow().async_step_init()
        self.schema.assert_called_once_with(
            "light", "custom", "<binary_sensor_id>_moon", "custom", "Moon",
        )

    async def test_legacy_naming_mode_still_opens(self):
        self.entry.options = {"entity_name_mode": "light"}
        await self.create_flow().async_step_init()
        self.schema.assert_called_once_with("switch", "night_sensor", "", "default", "")

    async def test_submit_options(self):
        user_input = {
            "entity_type": "light", "entity_name_mode": "custom",
            "custom_entity_name": "<light_entity_id>_night",
            "entity_display_name_mode": "custom", "custom_entity_display_name": "Moon",
        }
        result = await self.create_flow().async_step_init(user_input)
        self.assertEqual(result, {"type": "create_entry", "title": "", "data": user_input})
        self.schema.assert_not_called()


if __name__ == "__main__":
    unittest.main()
