# MC Repeater Stats

Publieke statistiekensite voor [MeshCore](https://meshcore.co.uk)-repeaters, gevoed
door Home Assistant. Bestaat uit twee delen:

- **`server/`** — FastAPI-website met publieke statistiekpagina's per repeater
  (status, batterij & solar, berichten, airtime, buren met SNR, grafieken), een
  beheerders-backend (`/admin`) en een token-beveiligde ingest-API.
- **`custom_components/mc_repeater_stats/`** — Home Assistant-integratie die de
  MeshCore-entiteiten in HA volgt en bij elke wijziging (gedebounced) een
  snapshot naar de site pusht.

## Zie ook

**[MeshCore Proxy](https://github.com/DinXke/MeshCore-Proxy)** — TCP-fanout-proxy
(Home Assistant add-on) waarmee meerdere companions (meshcore-ha, MeshCore-app,
meshcore-cli) tegelijk één MeshCore WiFi-node delen.

## Architectuur

```
MeshCore-integratie (HA)  →  entiteiten (sensor.meshcore_*)
                                   │  state-wijzigingen
                        MC Repeater Stats-integratie
                                   │  POST /api/v1/ingest  (Bearer-token)
                          website (LXC, achter cloudflared)
                                   │
                    publiek: /  en  /r/<slug>     beheer: /admin
```

## Server installeren (Debian LXC)

```bash
git clone https://github.com/DinXke/MC_Repeater_stats.git
cd MC_Repeater_stats
sudo bash deploy/install.sh
```

De service draait daarna op poort **8080** (systemd-unit `mc-repeater-stats`).
Bij de eerste start wordt een admin-account aangemaakt; het wachtwoord staat in
de log:

```bash
journalctl -u mc-repeater-stats | grep Wachtwoord
```

Log in op `/admin`, wijzig het wachtwoord en maak een **API-token** aan voor
Home Assistant.

### Cloudflared

Publiceer de site met een Cloudflare Tunnel die naar `http://localhost:8080`
wijst. De app draait met `--proxy-headers` en herkent `X-Forwarded-Proto`, dus
cookies werken correct achter de tunnel. Schemaloze bezoekers worden door
Cloudflare zelf naar HTTPS geleid.

### Wachtwoord kwijt?

```bash
echo 'nieuwwachtwoord' | sudo -u mcstats MCS_DATA_DIR=/var/lib/mc-repeater-stats \
  /opt/mc-repeater-stats/venv/bin/python -m app.main set-password admin
```

(uitvoeren vanuit `/opt/mc-repeater-stats/server`)

## Home Assistant-integratie installeren

1. Kopieer `custom_components/mc_repeater_stats/` naar `config/custom_components/`
   op je HA-instantie (of voeg deze repo toe als custom repository in HACS).
2. Herstart Home Assistant.
3. *Instellingen → Apparaten & diensten → Integratie toevoegen →*
   **MC Repeater Stats**.
4. Vul de website-URL en het API-token in.
5. Kies welke repeaters gesynchroniseerd worden (de integratie ontdekt ze
   automatisch op basis van de MeshCore-entiteiten).

Repeaters die je later toevoegt koppel je via *Opties* op de integratie. De
service `mc_repeater_stats.push_now` stuurt op verzoek meteen een volledige
snapshot.

## API

| Endpoint | Auth | Beschrijving |
|---|---|---|
| `GET /api/v1/ping` | Bearer | Verbindingstest |
| `POST /api/v1/ingest` | Bearer | Snapshot van één repeater |
| `GET /api/v1/repeaters` | — | Publieke repeaters + kerncijfers |
| `GET /api/v1/repeaters/{slug}` | — | Alle actuele metrics + buren |
| `GET /api/v1/repeaters/{slug}/history?metric=bat&hours=24` | — | Historiek voor grafieken |

Ingest-payload:

```json
{
  "repeater": {"pubkey_prefix": "e3d3f4d7ed", "name": "BE-HSS-JessaZH.VIR"},
  "metrics": {"bat": 4.15, "battery_percentage": 96.4, "online": true},
  "neighbors": [{"prefix": "2ae7af", "name": "BE-LUM-Lummen C-ESP", "snr": -4.25}]
}
```

Onbekende repeaters worden automatisch aangemaakt (standaard publiek; via
`/admin` te verbergen of hernoemen). Onbekende metrics komen in de sectie
"Overig" terecht.

## Databeheer

- Historiek wordt standaard **180 dagen** bewaard (`MCS_RETENTION_DAYS`).
- Een sample wordt alleen opgeslagen als de waarde wijzigde, met elke
  30 min een heartbeat-sample zodat grafieken doorlopen (`MCS_HEARTBEAT_MIN`).
- Data staat in `/var/lib/mc-repeater-stats/mcs.sqlite3`.
