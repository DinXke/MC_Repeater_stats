"""Config flow: URL + token invoeren, daarna repeaters kiezen."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import CONF_BASE_URL, CONF_REPEATERS, CONF_TOKEN, DOMAIN
from .pusher import discover_repeaters, validate_connection


def _repeater_options(hass) -> dict[str, str]:
    found = discover_repeaters(hass)
    return {prefix: f"{name} ({prefix})" for prefix, name in sorted(found.items(), key=lambda x: x[1])}


class McRepeaterStatsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._base_url: str | None = None
        self._token: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            try:
                ok = await validate_connection(self.hass, base_url, user_input[CONF_TOKEN])
            except Exception:  # noqa: BLE001
                ok = False
                errors["base"] = "cannot_connect"
            if ok:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                self._base_url = base_url
                self._token = user_input[CONF_TOKEN]
                return await self.async_step_repeaters()
            errors.setdefault("base", "invalid_auth")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_BASE_URL, default="https://"): cv.string,
                vol.Required(CONF_TOKEN): cv.string,
            }),
            errors=errors,
        )

    async def async_step_repeaters(self, user_input: dict[str, Any] | None = None):
        options = _repeater_options(self.hass)
        if user_input is not None:
            return self.async_create_entry(
                title=self._base_url,
                data={CONF_BASE_URL: self._base_url, CONF_TOKEN: self._token},
                options={CONF_REPEATERS: user_input[CONF_REPEATERS]},
            )
        return self.async_show_form(
            step_id="repeaters",
            data_schema=vol.Schema({
                vol.Required(CONF_REPEATERS, default=list(options)): cv.multi_select(options),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return McRepeaterStatsOptionsFlow()


class McRepeaterStatsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(data={CONF_REPEATERS: user_input[CONF_REPEATERS]})
        options = _repeater_options(self.hass)
        current = self.config_entry.options.get(CONF_REPEATERS, [])
        # bewaar ook eerder gekozen prefixen die nu (tijdelijk) geen entiteiten hebben
        for prefix in current:
            options.setdefault(prefix, prefix)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_REPEATERS, default=current or list(options)): cv.multi_select(options),
            }),
        )
