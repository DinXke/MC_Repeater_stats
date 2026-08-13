#!/usr/bin/env python3
"""MeshCore TCP-fanout-proxy.

De MeshCore companion-firmware accepteert maar één TCP-client tegelijk. Deze
proxy houdt die ene verbinding vast en laat meerdere clients (Home Assistant,
de MeshCore-app, meshcore-cli) tegelijk meekijken en commando's sturen:

  node (WiFi) <--- proxy ---> HA-integratie
                        \\---> MeshCore-app
                        \\---> meshcore-cli

- Client -> node: chunks worden geserialiseerd doorgestuurd (lock), zodat
  frames van twee clients nooit door elkaar raken.
- Node -> clients: elke chunk wordt naar alle verbonden clients gebroadcast;
  clients parsen zelf framegrenzen (het TCP-transport van MeshCore is een
  rauwe bytestream zonder framing).

Kanttekening: berichten ophalen is destructief in het companion-protocol —
de client die het eerst synct, consumeert het bericht. Met HA én de app
tegelijk verbonden kan een chatbericht dus bij één van beide belanden.
"""
import asyncio
import logging
import os

NODE_HOST = os.environ.get("MCP_NODE_HOST", "192.168.110.160")
NODE_PORT = int(os.environ.get("MCP_NODE_PORT", "5000"))
LISTEN_HOST = os.environ.get("MCP_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("MCP_LISTEN_PORT", "5000"))
RECONNECT_S = float(os.environ.get("MCP_RECONNECT_S", "1"))

log = logging.getLogger("mc-proxy")


class Proxy:
    def __init__(self) -> None:
        self.clients: set[asyncio.StreamWriter] = set()
        self.up_writer: asyncio.StreamWriter | None = None
        self.write_lock = asyncio.Lock()

    async def upstream_loop(self) -> None:
        """Houd de verbinding met de node in stand; herverbind bij verlies."""
        while True:
            try:
                reader, writer = await asyncio.open_connection(NODE_HOST, NODE_PORT)
                self.up_writer = writer
                log.info("verbonden met node %s:%s", NODE_HOST, NODE_PORT)
                while True:
                    data = await reader.read(4096)
                    if not data:
                        raise ConnectionError("node sloot de verbinding")
                    await self.broadcast(data)
            except Exception as err:  # noqa: BLE001
                if self.up_writer is not None:
                    log.warning("nodeverbinding verloren (%s); retry over %ss", err, RECONNECT_S)
                else:
                    log.info("node (nog) niet bereikbaar (%s); retry over %ss", err, RECONNECT_S)
                self.up_writer = None
                await asyncio.sleep(RECONNECT_S)

    async def broadcast(self, data: bytes) -> None:
        dead = []
        for w in list(self.clients):
            try:
                w.write(data)
                await w.drain()
            except Exception:  # noqa: BLE001
                dead.append(w)
        for w in dead:
            self.clients.discard(w)

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.clients.add(writer)
        log.info("client %s verbonden (%d actief)", peer, len(self.clients))
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                async with self.write_lock:
                    up = self.up_writer
                    if up is not None:
                        up.write(data)
                        await up.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.clients.discard(writer)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass
            log.info("client %s weg (%d over)", peer, len(self.clients))


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    proxy = Proxy()
    server = await asyncio.start_server(proxy.handle_client, LISTEN_HOST, LISTEN_PORT)
    log.info("mc-proxy luistert op %s:%s — node: %s:%s",
             LISTEN_HOST, LISTEN_PORT, NODE_HOST, NODE_PORT)
    async with server:
        await asyncio.gather(server.serve_forever(), proxy.upstream_loop())


if __name__ == "__main__":
    asyncio.run(main())
