from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from bot.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://serpapi.com/search.json"
MAX_FLEX_ITERATIONS = 14


class SerpAPIError(Exception):
    pass


class SerpAPIClient:
    def __init__(self, settings: Settings) -> None:
        self._key = settings.serpapi_key.get_secret_value()
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "api_key": self._key}
        resp = await self._client.get(BASE_URL, params=params)
        if resp.status_code != 200:
            raise SerpAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data: dict[str, Any] = resp.json()
        if "error" in data:
            raise SerpAPIError(str(data["error"]))
        return data

    async def search_flights(
        self,
        origin_iata: str,
        destination_iata: str,
        depart_date: str,
        return_date: str | None = None,
        adults: int = 1,
        currency: str = "BRL",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": origin_iata,
            "arrival_id": destination_iata,
            "outbound_date": depart_date,
            "adults": adults,
            "currency": currency,
            "hl": "pt-br",
            "gl": "br",
            "type": "2" if return_date is None else "1",
        }
        if return_date:
            params["return_date"] = return_date
        return await self._get(params)

    async def search_hotels(
        self,
        location: str,
        check_in: str,
        check_out: str,
        adults: int = 2,
        currency: str = "BRL",
    ) -> dict[str, Any]:
        params = {
            "engine": "google_hotels",
            "q": location,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": adults,
            "currency": currency,
            "hl": "pt-br",
            "gl": "br",
        }
        return await self._get(params)


async def find_best_hotel_in_window(
    serpapi: "SerpAPIClient",
    location: str,
    window_start: str,
    window_end: str,
    nights: int,
    adults: int = 2,
    currency: str = "BRL",
) -> tuple[float, dict[str, Any], str, str] | None:
    try:
        start = date.fromisoformat(window_start)
        end = date.fromisoformat(window_end)
    except ValueError:
        return None
    last_checkin = end - timedelta(days=nights)
    if last_checkin < start or nights <= 0:
        return None
    span = (last_checkin - start).days + 1
    iterations = min(span, MAX_FLEX_ITERATIONS)
    best: tuple[float, dict[str, Any], str, str] | None = None
    for i in range(iterations):
        ci = (start + timedelta(days=i)).isoformat()
        co = (start + timedelta(days=i + nights)).isoformat()
        try:
            raw = await serpapi.search_hotels(location, ci, co, adults, currency)
        except SerpAPIError as e:
            logger.warning("flex hotel leg %s→%s failed: %s", ci, co, e)
            continue
        leg = extract_best_hotel(raw)
        if leg is None:
            continue
        price, payload = leg
        if best is None or price < best[0]:
            best = (price, payload, ci, co)
    return best


def extract_best_flight(raw: dict[str, Any]) -> tuple[float, dict[str, Any]] | None:
    candidates: list[dict[str, Any]] = []
    candidates.extend(raw.get("best_flights") or [])
    candidates.extend(raw.get("other_flights") or [])
    if not candidates:
        return None
    priced = [c for c in candidates if isinstance(c.get("price"), (int, float))]
    if not priced:
        return None
    best = min(priced, key=lambda c: c["price"])
    return float(best["price"]), best


def extract_best_hotel(raw: dict[str, Any]) -> tuple[float, dict[str, Any]] | None:
    properties = raw.get("properties") or []
    priced: list[tuple[float, dict[str, Any]]] = []
    for p in properties:
        rate = p.get("rate_per_night") or p.get("total_rate")
        if not isinstance(rate, dict):
            continue
        val = rate.get("extracted_lowest") or rate.get("lowest")
        if isinstance(val, str):
            try:
                val = float(val.replace("R$", "").replace(".", "").replace(",", ".").strip())
            except ValueError:
                continue
        if isinstance(val, (int, float)):
            priced.append((float(val), p))
    if not priced:
        return None
    return min(priced, key=lambda t: t[0])


def _fmt_duration(mins: Any) -> str:
    if not isinstance(mins, (int, float)) or mins <= 0:
        return "?"
    h, m = divmod(int(mins), 60)
    if h and m:
        return f"{h}h{m:02d}"
    if h:
        return f"{h}h"
    return f"{m}min"


def _fmt_time(s: Any) -> str:
    if not isinstance(s, str) or not s:
        return "?"
    parts = s.split(" ")
    return parts[1] if len(parts) > 1 else s


def format_flight(price: float, payload: dict[str, Any]) -> str:
    lines: list[str] = [f"💰 <b>R$ {price:.2f}</b>"]

    total_duration = payload.get("total_duration")
    if total_duration:
        lines.append(f"⏱ Duração total: {_fmt_duration(total_duration)}")

    trip_type = payload.get("type")
    if trip_type:
        lines.append(f"🔁 {trip_type}")

    flights = payload.get("flights") or []
    layovers = payload.get("layovers") or []
    lines.append("")

    for i, flight in enumerate(flights):
        airline = flight.get("airline", "?")
        flight_number = flight.get("flight_number", "")
        airplane = flight.get("airplane") or ""
        travel_class = flight.get("travel_class") or ""

        dep = flight.get("departure_airport") or {}
        arr = flight.get("arrival_airport") or {}

        header = f"<b>{airline} {flight_number}</b>".rstrip()
        details: list[str] = []
        if travel_class:
            details.append(travel_class)
        if airplane:
            details.append(airplane)
        if details:
            header += f" — {' / '.join(details)}"
        lines.append(header)

        dep_name = dep.get("name") or "?"
        dep_id = dep.get("id") or ""
        arr_name = arr.get("name") or "?"
        arr_id = arr.get("id") or ""
        lines.append(f"  🛫 {_fmt_time(dep.get('time'))} {dep_name} ({dep_id})")
        lines.append(f"  🛬 {_fmt_time(arr.get('time'))} {arr_name} ({arr_id})")

        leg_dur = flight.get("duration")
        if leg_dur:
            lines.append(f"  ⏱ {_fmt_duration(leg_dur)}")

        if flight.get("overnight"):
            lines.append("  🌙 voo noturno")

        if i < len(layovers):
            lay = layovers[i]
            lay_name = lay.get("name") or lay.get("id") or "?"
            lines.append(
                f"  ⤷ Conexão em {lay_name}: {_fmt_duration(lay.get('duration'))}"
            )

    extensions = payload.get("extensions") or []
    if extensions:
        lines.append("")
        for ext in extensions[:4]:
            lines.append(f"• {ext}")

    return "\n".join(lines)


def format_hotel(
    price: float,
    payload: dict[str, Any],
    chosen_check_in: str | None = None,
    chosen_check_out: str | None = None,
) -> str:
    name = payload.get("name") or "Hotel"
    hotel_class = payload.get("hotel_class") or ""
    rating = payload.get("overall_rating")
    reviews = payload.get("reviews")
    check_in = payload.get("check_in_time")
    check_out = payload.get("check_out_time")
    amenities = payload.get("amenities") or []
    description = payload.get("description")
    nearby = payload.get("nearby_places") or []
    link = payload.get("link")

    lines: list[str] = [f"💰 <b>R$ {price:.2f}</b> / diária"]
    if chosen_check_in and chosen_check_out:
        try:
            ci = date.fromisoformat(chosen_check_in)
            co = date.fromisoformat(chosen_check_out)
            nights = (co - ci).days
            lines.append(
                f"📅 {ci.strftime('%d/%m')} → {co.strftime('%d/%m')} ({nights} noite{'s' if nights != 1 else ''})"
            )
        except ValueError:
            lines.append(f"📅 {chosen_check_in} → {chosen_check_out}")
    lines.append(f"🏨 <b>{name}</b>")
    if hotel_class:
        lines.append(f"  {hotel_class}")
    if rating:
        rating_line = f"  ⭐ {rating}"
        if reviews:
            rating_line += f" ({reviews} avaliações)"
        lines.append(rating_line)
    if check_in or check_out:
        lines.append(
            f"  🕐 Check-in {check_in or '?'} · Check-out {check_out or '?'}"
        )
    if amenities:
        top = amenities[:6]
        lines.append(f"  ✨ {', '.join(str(a) for a in top)}")
    if nearby:
        first = nearby[0]
        if isinstance(first, dict) and first.get("name"):
            transp = first.get("transportations") or []
            extra = ""
            if transp and isinstance(transp[0], dict):
                extra = f" ({transp[0].get('duration', '')} {transp[0].get('type', '')})".strip()
            lines.append(f"  📍 Perto de: {first['name']}{extra}")
    if description:
        lines.append("")
        text = str(description)
        lines.append(text[:300] + ("…" if len(text) > 300 else ""))
    if link:
        lines.append("")
        lines.append(f'🔗 <a href="{link}">Ver no Google Hotels</a>')

    return "\n".join(lines)
