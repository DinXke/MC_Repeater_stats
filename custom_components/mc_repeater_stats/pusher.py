"""Verzamelt MeshCore-repeaterdata uit de HA-state-machine en pusht die naar de site."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    DEBOUNCE_SECONDS,
    FULL_PUSH_INTERVAL,
    KNOWN_METRICS,
    RE_ENTITY,
    RE_NAME,
    RE_NEIGHBOR,
    RE_NEIGHBOR_NAME,
    RE_NEIGHBOR_SEEN,
)

_LOGGER = logging.getLogger(__name__)


def discover_repeaters(hass: HomeAssistant) -> dict[str, str]:
    """Alle meshcore-prefixen in de state-machine -> weergavenaam."""
    found: dict[str, str] = {}
    for state in hass.states.async_all(("sensor", "binary_sensor")):
        m = RE_ENTITY.match(state.entity_id)
        if not m:
            continue
        prefix = m.group(1)
        name = found.get(prefix, "")
        if not name:
            friendly = state.attributes.get("friendly_name") or ""
            nm = RE_NAME.search(friendly)
            found[prefix] = nm.group(1) if nm else prefix
    return found


def extract_metric(rest: str) -> str | None:
    """Metricnaam uit het entity-id-deel na de prefix (knipt de nodenaam-suffix af)."""
    for metric in KNOWN_METRICS:
        if rest == metric or rest.startswith(metric + "_"):
            return metric
    return None


class Pusher:
    """Luistert naar state-wijzigingen en pusht (met debounce) snapshots per repeater."""

    def __init__(self, hass: HomeAssistant, base_url: str, token: str, prefixes: list[str]) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.prefixes = set(prefixes)
        self._session = async_get_clientsession(hass)
        self._unsub: list = []
        self._debounce: dict[str, Any] = {}

    async def async_start(self) -> None:
        self._unsub.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_state_changed))
        self._unsub.append(
            async_track_time_interval(
                self.hass, self._interval_push, timedelta(seconds=FULL_PUSH_INTERVAL)
            )
        )
        await self.push_all()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        for cancel in self._debounce.values():
            cancel()
        self._debounce.clear()

    @callback
    def _on_state_changed(self, event: Event) -> None:
        m = RE_ENTITY.match(event.data.get("entity_id", ""))
        if not m or m.group(1) not in self.prefixes:
            return
        prefix = m.group(1)
        if prefix in self._debounce:
            return  # er staat al een push gepland
        self._debounce[prefix] = async_call_later(
            self.hass, DEBOUNCE_SECONDS, self._make_debounced(prefix)
        )

    def _make_debounced(self, prefix: str):
        async def _run(_now) -> None:
            self._debounce.pop(prefix, None)
            await self.push_repeater(prefix)
        return _run

    async def _interval_push(self, _now) -> None:
        await self.push_all()

    async def push_all(self) -> None:
        for prefix in self.prefixes:
            await self.push_repeater(prefix)

    def _snapshot(self, prefix: str) -> dict | None:
        metrics: dict[str, Any] = {}
        neighbors: dict[str, dict] = {}
        name = prefix
        for state in self.hass.states.async_all(("sensor", "binary_sensor")):
            m = RE_ENTITY.match(state.entity_id)
            if not m or m.group(1) != prefix:
                continue
            friendly = state.attributes.get("friendly_name") or ""
            nm = RE_NAME.search(friendly)
            if nm:
                name = nm.group(1)
            if state.state in ("unknown", "unavailable", ""):
                continue
            rest = m.group(2)
            nbs = RE_NEIGHBOR_SEEN.match(rest)
            if nbs:
                try:
                    seen = float(state.state)  # minuten sinds laatst gehoord
                except ValueError:
                    continue
                neighbors.setdefault(nbs.group(1), {"prefix": nbs.group(1)})["seen_min"] = seen
                continue
            nb = RE_NEIGHBOR.match(rest)
            if nb:
                try:
                    snr = float(state.state)
                except ValueError:
                    continue
                entry = neighbors.setdefault(nb.group(1), {"prefix": nb.group(1)})
                entry["snr"] = snr
                nn = RE_NEIGHBOR_NAME.search(friendly)
                if nn:
                    entry["name"] = nn.group(1)
                continue
            metric = extract_metric(rest)
            if metric is None:
                continue
            if state.entity_id.startswith("binary_sensor."):
                # 'contact' meldt fresh/stale; alles anders dan on/fresh is offline
                metrics[metric] = state.state in ("on", "fresh")
            else:
                try:
                    metrics[metric] = float(state.state)
                except ValueError:
                    metrics[metric] = state.state
        if not metrics:
            return None
        return {
            "repeater": {"pubkey_prefix": prefix, "name": name},
            "metrics": metrics,
            "neighbors": list(neighbors.values()),
        }

    async def push_repeater(self, prefix: str) -> bool:
        payload = self._snapshot(prefix)
        if payload is None:
            _LOGGER.debug("Geen data voor repeater %s, push overgeslagen", prefix)
            return False
        try:
            resp = await self._session.post(
                f"{self.base_url}/api/v1/ingest",
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30,
            )
            if resp.status >= 400:
                _LOGGER.warning(
                    "Push voor %s geweigerd door %s: HTTP %s",
                    prefix, self.base_url, resp.status,
                )
                return False
            return True
        except Exception as err:  # noqa: BLE001 - netwerkfouten mogen de loop niet breken
            _LOGGER.warning("Push voor %s naar %s mislukt: %s", prefix, self.base_url, err)
            return False


async def validate_connection(hass: HomeAssistant, base_url: str, token: str) -> bool:
    session = async_get_clientsession(hass)
    resp = await session.get(
        f"{base_url.rstrip('/')}/api/v1/ping",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return resp.status == 200
