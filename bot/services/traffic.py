from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from urllib.parse import quote, unquote_plus

import httpx

logger = logging.getLogger(__name__)

DIRECTIONS_ENDPOINT = "https://maps.googleapis.com/maps/api/directions/json"
USER_AGENT = (
    "Mozilla/5.0 (compatible; TelegramTravelsBot/0.2; "
    "+https://github.com/srocupado/telegram-travels)"
)
MAX_WAYPOINTS = 23
SHORT_LINK_HOSTS = ("maps.app.goo.gl", "goo.gl")


class TrafficError(Exception):
    pass


@dataclass(frozen=True)
class TrafficInfo:
    duration_minutes: int
    typical_minutes: int
    distance_km: float
    summary: str
    maps_url: str


async def parse_route_waypoints(client: httpx.AsyncClient, url: str) -> list[str]:
    if not url:
        return []
    expanded = url
    parsed = httpx.URL(url)
    if parsed.host in SHORT_LINK_HOSTS:
        try:
            resp = await client.get(url, follow_redirects=True)
            expanded = str(resp.url)
        except httpx.HTTPError as e:
            raise TrafficError(f"failed to expand short URL: {e}") from e

    marker = "/dir/"
    idx = expanded.find(marker)
    if idx < 0:
        return []
    tail = expanded[idx + len(marker):]
    # cut at viewport (@) or data= or query string
    cut_positions = [len(tail)]
    for sep in ("/@", "/data=", "?"):
        p = tail.find(sep)
        if p >= 0:
            cut_positions.append(p)
    tail = tail[: min(cut_positions)]

    raw_segments = [s for s in tail.split("/") if s]
    segments = [unquote_plus(s) for s in raw_segments]
    if len(segments) <= 2:
        return []
    middle = segments[1:-1]
    if len(middle) > MAX_WAYPOINTS:
        logger.warning(
            "route URL has %d waypoints, capping at %d", len(middle), MAX_WAYPOINTS
        )
        middle = middle[:MAX_WAYPOINTS]
    return middle


def _format_waypoints(waypoints: list[str]) -> str:
    parts = []
    for w in waypoints:
        parts.append(f"via:{w}")
    return "|".join(parts)


async def fetch_traffic(
    client: httpx.AsyncClient,
    api_key: str,
    origin: str,
    destination: str,
    waypoints: list[str],
    maps_url: str = "",
) -> TrafficInfo:
    params = {
        "origin": origin,
        "destination": destination,
        "departure_time": "now",
        "traffic_model": "best_guess",
        "mode": "driving",
        "key": api_key,
    }
    if waypoints:
        params["waypoints"] = _format_waypoints(waypoints)

    try:
        resp = await client.get(DIRECTIONS_ENDPOINT, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise TrafficError(f"directions request failed: {e}") from e

    data = resp.json()
    status = data.get("status")
    if status != "OK":
        msg = data.get("error_message") or status or "unknown error"
        raise TrafficError(f"directions API status={status}: {msg}")

    routes = data.get("routes") or []
    if not routes:
        raise TrafficError("directions API returned no routes")
    route = routes[0]
    legs = route.get("legs") or []
    if not legs:
        raise TrafficError("directions API route has no legs")

    duration_traffic_s = 0
    duration_typical_s = 0
    distance_m = 0
    for leg in legs:
        dt = (leg.get("duration_in_traffic") or {}).get("value")
        d = (leg.get("duration") or {}).get("value")
        dist = (leg.get("distance") or {}).get("value")
        duration_traffic_s += int(dt if dt is not None else d or 0)
        duration_typical_s += int(d or 0)
        distance_m += int(dist or 0)

    summary = route.get("summary") or ""

    fallback_origin = quote(origin, safe=",")
    fallback_dest = quote(destination, safe=",")
    fallback_url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={fallback_origin}&destination={fallback_dest}&travelmode=driving"
    )

    return TrafficInfo(
        duration_minutes=max(1, round(duration_traffic_s / 60)),
        typical_minutes=max(1, round(duration_typical_s / 60)),
        distance_km=round(distance_m / 1000, 1),
        summary=summary,
        maps_url=maps_url or fallback_url,
    )


def _severity_emoji(duration: int, typical: int) -> str:
    if typical <= 0:
        return "🟢"
    delta_ratio = (duration - typical) / typical
    if delta_ratio < 0.10:
        return "🟢"
    if delta_ratio < 0.25:
        return "🟡"
    return "🔴"


def format_traffic_message(info: TrafficInfo, when_label: str) -> str:
    delta = info.duration_minutes - info.typical_minutes
    emoji = _severity_emoji(info.duration_minutes, info.typical_minutes)
    if delta > 0:
        delta_line = f"{emoji} +{delta} min de trânsito"
    elif delta < 0:
        delta_line = f"{emoji} {delta} min vs típico"
    else:
        delta_line = f"{emoji} sem trânsito acima do normal"

    via = f" via {html.escape(info.summary)}" if info.summary else ""
    label = html.escape(when_label)
    lines = [
        f"🚗 <b>Trânsito {label}</b>",
        "",
        f"⏱️ <b>~{info.duration_minutes} min agora</b> (típico: ~{info.typical_minutes} min)",
        delta_line,
        f"📏 {info.distance_km} km{via}",
    ]
    if info.maps_url:
        lines.append("")
        lines.append(f'<a href="{html.escape(info.maps_url, quote=True)}">abrir no Google Maps</a>')
    return "\n".join(lines)
