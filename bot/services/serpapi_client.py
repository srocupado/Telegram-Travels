from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://serpapi.com/search.json"


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
