# MeshCore Proxy

De MeshCore companion-firmware laat maar één TCP-client tegelijk toe. Deze
add-on houdt die ene verbinding met je WiFi-node vast en laat meerdere
clients tegelijk meekijken en commando's sturen:

```
WiFi-node  <-->  MeshCore Proxy (deze add-on)  <-->  meshcore-integratie (127.0.0.1)
                                               <-->  MeshCore-app (HA-IP:5000)
                                               <-->  meshcore-cli
```

## Configuratie

| Optie | Betekenis |
|---|---|
| `node_host` | IP van je MeshCore WiFi-node |
| `node_port` | TCP-poort van de node (standaard 5000) |
| `listen_port` | Poort waarop de proxy luistert (standaard 5000) |

## Gebruik

1. Start de add-on.
2. Zet de **meshcore-integratie** op TCP-host `127.0.0.1`, poort `5000`
   (de add-on draait met host-netwerk, dus localhost werkt).
3. Verbind je **MeshCore-app** met `<IP-van-je-HA>` poort `5000`.

## Kanttekening

Berichten ophalen is destructief in het companion-protocol: de client die het
eerst synchroniseert, consumeert het bericht. Met HA én de app tegelijk
verbonden kan een chatbericht dus bij één van beide belanden. Voor
statistieken en beheer maakt dit niets uit.
