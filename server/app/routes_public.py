"""Publieke HTML-pagina's."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import config, db, metrics
from .templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    rows = db.q("SELECT * FROM repeaters WHERE is_public=1 ORDER BY sort_order, name")
    cards = []
    for r in rows:
        latest = db.latest_for(r["id"])
        def val(m):
            row = latest.get(m)
            return None if row is None or row["value"] is None else row["value"]
        cards.append({
            "slug": r["slug"], "name": r["name"], "prefix": r["pubkey_prefix"],
            "last_seen": r["last_seen"],
            "online": val("online") == 1.0,
            "battery": val("battery_percentage"),
            "uptime": val("uptime"),
            "neighbors": val("neighbor_count"),
        })
    return templates.TemplateResponse(request, "index.html", {
        "site_name": config.SITE_NAME, "cards": cards,
    })


@router.get("/r/{slug}", response_class=HTMLResponse)
def repeater_page(request: Request, slug: str):
    r = db.qone("SELECT * FROM repeaters WHERE slug=? AND is_public=1", (slug,))
    if not r:
        raise HTTPException(404, "Onbekende repeater")
    latest = db.latest_for(r["id"])

    sections = []
    used = set()
    for key, title in metrics.SECTIONS:
        tiles = []
        for m in metrics.TILE_METRICS.get(key, []):
            row = latest.get(m)
            if row is None:
                continue
            used.add(m)
            _, label, unit, _ = metrics.metric_info(m)
            tiles.append(_tile(m, label, unit, row))
        # metrics die wel binnenkwamen maar niet in de vaste tegellijst staan
        extra = []
        for m, row in latest.items():
            if m in used:
                continue
            section, label, unit, sort = metrics.metric_info(m)
            if section == key:
                extra.append((sort, _tile(m, label, unit, row)))
        tiles += [t for _, t in sorted(extra, key=lambda x: x[0])]
        for _, t in sorted(extra, key=lambda x: x[0]):
            used.add(t["metric"])
        if tiles:
            sections.append({"key": key, "title": title, "tiles": tiles})

    neighbors = db.q("SELECT * FROM neighbors WHERE repeater_id=? ORDER BY snr DESC", (r["id"],))
    charts = [
        {"title": title, "metrics": mets, "hours": hours,
         "labels": [metrics.metric_info(m)[1] for m in mets],
         "unit": metrics.metric_info(mets[0])[2]}
        for title, mets, hours in metrics.CHARTS
        if any(m in latest for m in mets)
    ]
    return templates.TemplateResponse(request, "repeater.html", {
        "site_name": config.SITE_NAME, "r": r, "sections": sections,
        "neighbors": neighbors, "charts": charts, "gauges": metrics.GAUGES,
    })


def _tile(metric: str, label: str, unit: str | None, row) -> dict:
    value = row["value"]
    display = row["value_str"] or "—"
    if value is not None:
        if metric == "online":
            display = "Online" if value == 1.0 else "Offline"
        elif metric == "uptime":
            display = _fmt_uptime(value)
        elif value == int(value) and abs(value) < 1e9:
            display = f"{int(value):,}".replace(",", " ")
        else:
            display = f"{value:g}"
        if unit and metric not in ("online", "uptime"):
            display += f" {unit}"
    return {"metric": metric, "label": label, "value": value, "display": display, "ts": row["ts"]}


def _fmt_uptime(days: float) -> str:
    total_min = int(days * 24 * 60)
    d, rest = divmod(total_min, 24 * 60)
    h, m = divmod(rest, 60)
    if d:
        return f"{d} d {h} u"
    if h:
        return f"{h} u {m} min"
    return f"{m} min"
