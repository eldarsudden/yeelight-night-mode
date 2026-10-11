<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/yeelight_night_mode/brand/dark_icon.png">
  <img src="custom_components/yeelight_night_mode/brand/icon.png" width="80" height="80" alt="Yeelight Night Mode">
</picture>
# Yeelight Night Mode



A custom Home Assistant integration for controlling the moonlight/nightlight mode of Yeelight lights. It creates an entity for each supported light and a group switch for each area.

Commands use the built-in `yeelight` integration through the `yeelight.set_mode` action. Night mode state comes from that integration's binary sensor.

## Features

- Expose each light's night mode as a **switch** or a **light**. The `light` option supports on/off control without brightness or color settings.
- Automatically create area group **switches**, including when individual entities use the `light` type.
- Customize display names and entity ID templates for individual lights.
- Update group membership when lights move between areas.
- Attach individual night mode entities to existing Yeelight devices when a matching device is found in the Home Assistant registry.

Version **2.3.0** adds area group switches and updates the integration's PNG icon.

## Prerequisites

First, add your lights to the built-in **Yeelight** integration and check that you can control them from Home Assistant. A light must have a night mode binary sensor registered by that integration for its night mode entity to be created.

If a discovered sensor is disabled, Yeelight Night Mode automatically enables it because its state is required. If no such sensor exists, no night mode entity is created for that light.

For group control, assign the source `light.*` entity or its device to a Home Assistant area. Lights without an area can still be controlled individually.

## Installation

### Through HACS

1. Open **Custom repositories** in HACS.
2. Add `https://github.com/eldarsudden/yeelight-night-mode` with the **Integration** category.
3. Find **Yeelight Night Mode** and install it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and select **Yeelight Night Mode**.
6. Choose the individual entity type, display name, and entity ID naming scheme.

### Manual installation

1. Copy `custom_components/yeelight_night_mode` from this repository into the `custom_components` directory of your Home Assistant configuration.
2. Restart Home Assistant.
3. Add **Yeelight Night Mode** through **Settings → Devices & services**.

Configuration is handled through the Home Assistant UI. Only one instance of the integration is allowed.

## Individual entity settings

These settings are available during setup and later through the integration's **Options / Configure** dialog. Saving changes reloads the integration.

| Setting | Purpose | Default |
| --- | --- | --- |
| **Entity type** | Entity type for each light: `switch` or `light` | `switch` |
| **Entity ID naming** | Use the source sensor ID (`Night sensor entity ID`) or a custom template (`Custom`) | `Night sensor entity ID` |
| **Custom entity ID** | Entity ID template when `Custom` is selected | — |
| **Entity name** | Use the default display name or `Custom` | `Nightlight Mode` |
| **Custom entity name** | Display name when `Custom` is selected | — |

Entity IDs and display names are configured separately. These settings apply to individual entities; group switches use their own area-based names and IDs.

### Entity ID templates

**Night sensor entity ID** uses the part of the binary sensor's ID after the dot. For example, `binary_sensor.ceilb_0x24f96a4f_nightlight` produces `switch.ceilb_0x24f96a4f_nightlight` when the `switch` type is selected.

**Custom** supports these placeholders:

| Placeholder | Value |
| --- | --- |
| `<binary_sensor_id>` | The part of the night mode sensor's ID after the dot |
| `<light_entity_id>` | The part of the source Yeelight `light.*` entity's ID after the dot |

Enter a template without the `switch.` or `light.` prefix, for example:

```text
<light_entity_id>_night_mode
```

For the source light `light.ceilb_0x24f96a4f`, the result depends on the selected type:

| Entity type | Night mode entity ID |
| --- | --- |
| `switch` | `switch.ceilb_0x24f96a4f_night_mode` |
| `light` | `light.ceilb_0x24f96a4f_night_mode` |

With multiple lights, use a template that produces a unique ID for each light. These examples assume the resulting IDs are available in Home Assistant.

## Area group switches

A separate **switch** is created automatically for each area containing discovered Yeelight lights that support night mode. Groups are also created for areas with just one eligible light, regardless of the individual entity type.

For example, an area named “Bedroom” with the ID `bedroom` gets the suggested entity ID:

```text
switch.yeelight_bedroom_night_mode
```

With the UI set to English, its display name is **Yeelight Nightlight Mode · Bedroom**. The switch is assigned to the corresponding area. Renaming the area updates the display name while preserving the group's entity ID.

### Group membership

The area is resolved from the **source Yeelight `light.*` entity**:

1. If the entity has an explicitly assigned area, that area is used.
2. Otherwise, the entity's device area is used.
3. If neither has an area, the light is excluded from area groups.

Only discovered lights that support night mode and have both their source `light.*` and binary sensor entities enabled are included. Other lights in the same area are excluded.

Moving a light between areas, changing an entity's area, or renaming source entity IDs automatically updates the groups. An empty group remains unavailable, preserving its entity ID and user customizations in case lights return to it.

### State and commands

| Action or state | Group behavior |
| --- | --- |
| Turn on | Set available lights in the group to `moonlight` |
| Turn off | Set available lights in the group to `normal` |
| `on` | At least one available light has night mode enabled |
| `off` | Available lights exist, and all have night mode disabled |
| `unavailable` | No lights are available, or the group is empty |

A light is considered available to the group when both its source `light.*` entity and night mode sensor have an `on` or `off` state. Lights with missing, `unknown`, or `unavailable` states are skipped.

Group state follows the source sensors. After a command, the displayed state may take time to change while those sensors update.

## Actions and automations

Enable night mode for all available Yeelight lights in the bedroom:

```yaml
action: switch.turn_on
target:
  entity_id: switch.yeelight_bedroom_night_mode
```

Return those lights to normal mode:

```yaml
action: switch.turn_off
target:
  entity_id: switch.yeelight_bedroom_night_mode
```

For an individual `switch` entity, use the same actions with its entity ID. For the `light` type, use `light.turn_on` and `light.turn_off`.

Turning off a Night Mode entity selects **normal** mode rather than sending a power-off command to the light.

### Entity attributes

| Entity | Attribute | Value |
| --- | --- | --- |
| Individual | `ip_address` | The light's IP address recorded during discovery |
| Individual | `night_sensor_entity_id` | The source night mode sensor |
| Individual | `light_entity_id` | The source Yeelight light entity, if found |
| Group | `area_id` | The group's area ID |
| Group | `entity_id` | Source Yeelight light entities in the group, including temporarily unavailable members |

## Updates and troubleshooting

- **After updating the integration files**, restart Home Assistant. When upgrading from 2.2.x, group switches appear automatically for eligible areas.
- **After adding new Yeelight devices**, reload Yeelight Night Mode to discover them. Restarting Home Assistant also runs discovery.
- **An individual entity is missing:** check that the built-in Yeelight integration has a related night mode binary sensor. Being a Yeelight light alone does not guarantee night mode support.
- **An individual entity is unavailable:** check the source binary sensor's state. The entity remains unavailable until that sensor reports a state.
- **An area group switch is missing:** check the area assigned to the source `light.*` entity or its device, and make sure both source entities exist and are enabled.
- **An area group switch is unavailable:** check the source light and sensor states. At least one available pair is required.
- **After renaming a source light or sensor entity ID**, groups update automatically. Reload the integration to update the references used by individual entities.

Control requires an available source Yeelight `light.*` entity and a working `yeelight.set_mode` action. This integration uses devices discovered through the built-in integration; it cannot add night mode support to models that lack it.

## Development

Run the checks for grouping, states, commands, registry changes, and platform loading from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The tests use an in-memory stand-in for the Home Assistant API and require neither lights nor a running Home Assistant instance. They do not replace validation in a real Home Assistant installation.

Main files:

| File | Purpose |
| --- | --- |
| `custom_components/yeelight_night_mode/__init__.py` | Platform setup and unloading |
| `custom_components/yeelight_night_mode/config_flow.py` | UI configuration |
| `custom_components/yeelight_night_mode/discovery.py` | Discovery of eligible lights |
| `custom_components/yeelight_night_mode/entity.py` | Shared logic for individual entities |
| `custom_components/yeelight_night_mode/switch.py`, `light.py` | Individual entity platforms |
| `custom_components/yeelight_night_mode/area.py` | Area group switches and membership updates |
| `custom_components/yeelight_night_mode/brand/` | PNG icons for light and dark themes |
| `tests/test_area.py` | Group behavior and platform loading checks |

## Icon and license

The PNG icon uses Google's **Material Symbols Outlined — moon_stars** (FILL 0, weight 400, grade 0, optical size 24), distributed under the Apache License 2.0. Both variants are 256 × 256 with transparent backgrounds. Source details are in [brand/README.md](custom_components/yeelight_night_mode/brand/README.md).

The integration code is distributed under the [BSD 2-Clause License](LICENSE).
