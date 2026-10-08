"""HTTP client for ESPN's (unofficial) fantasy football v3 API.

Handles cookies, the X-Fantasy-Filter header, retries with backoff on transient
failures, and turns ESPN's failure modes into typed errors.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
# ESPN's public NFL scoreboard (game states, clocks, scores). No auth, separate host.
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class EspnError(Exception):
    """Any ESPN failure."""


class EspnAuthError(EspnError):
    """Cookies missing, invalid, or expired (or the league is private)."""


class EspnNotFoundError(EspnError):
    """League or season does not exist."""


class _TransientError(EspnError):
    """Retryable: network error, 429, or 5xx."""


class EspnClient:
    def __init__(
        self,
        *,
        espn_s2: str | None = None,
        swid: str | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        cookies = {}
        if espn_s2 and swid:
            cookies = {"espn_s2": espn_s2, "SWID": swid}
        self.swid = swid
        self._http = httpx.Client(
            base_url=BASE_URL,
            cookies=cookies,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "fantasy-gm/0.1"},
            follow_redirects=False,
        )
        # No cookies here: fantasy auth has no business going to another host. Also keep
        # httpx's default User-Agent: this host answers 403 to custom ones (verified).
        self._scoreboard_http = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()
        self._scoreboard_http.close()

    def __enter__(self) -> EspnClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- endpoints -----------------------------------------------------------

    def league(
        self,
        league_id: str | int,
        season: int,
        views: list[str],
        *,
        scoring_period: int | None = None,
        fantasy_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: list[tuple[str, str]] = [("view", v) for v in views]
        if scoring_period is not None:
            params.append(("scoringPeriodId", str(scoring_period)))
        data = self._get(
            f"/seasons/{season}/segments/0/leagues/{league_id}",
            params,
            fantasy_filter,
            what=f"league {league_id} (season {season})",
        )
        if not isinstance(data, dict):
            raise EspnError("Unexpected league response shape from ESPN")
        return data

    def free_agents(
        self, league_id: str | int, season: int, *, scoring_period: int, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Available players (free agents + waivers), most-rostered first."""
        fantasy_filter = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "filterSlotIds": {"value": [0, 2, 4, 6, 16, 17]},
                "limit": limit,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "filterStatsForTopScoringPeriodIds": {
                    "value": 2,
                    "additionalValue": [
                        f"00{season}",
                        f"10{season}",
                        f"11{season}{scoring_period}",
                    ],
                },
            }
        }
        data = self.league(
            league_id,
            season,
            ["kona_player_info"],
            scoring_period=scoring_period,
            fantasy_filter=fantasy_filter,
        )
        return data.get("players") or []

    def nfl_scoreboard(self, season: int, week: int) -> dict[str, Any]:
        """Every NFL game of a regular-season week, with live state and score."""
        try:
            response = self._scoreboard_http.get(
                SCOREBOARD_URL, params={"dates": season, "seasontype": 2, "week": week}
            )
        except httpx.TransportError as e:
            raise EspnError(f"Could not reach the NFL scoreboard: {type(e).__name__}") from e
        if response.status_code >= 400:
            raise EspnError(f"NFL scoreboard returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as e:
            raise EspnError("NFL scoreboard returned non-JSON") from e
        if not isinstance(data, dict):
            raise EspnError("Unexpected NFL scoreboard response shape")
        return data

    # --- plumbing ------------------------------------------------------------

    def _get(
        self,
        path: str,
        params: list[tuple[str, str]],
        fantasy_filter: dict[str, Any] | None,
        *,
        what: str,
    ) -> Any:
        headers = {}
        if fantasy_filter is not None:
            headers["X-Fantasy-Filter"] = json.dumps(fantasy_filter)
        response = self._send(path, params, headers)
        return self._parse(response, what)

    @retry(
        retry=retry_if_exception_type(_TransientError),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=15),
        reraise=True,
    )
    def _send(
        self, path: str, params: list[tuple[str, str]], headers: dict[str, str]
    ) -> httpx.Response:
        try:
            response = self._http.get(path, params=params, headers=headers)
        except httpx.TransportError as e:
            log.warning("ESPN request failed (%s), retrying", type(e).__name__)
            raise _TransientError(f"Could not reach ESPN: {type(e).__name__}") from e
        if response.status_code == 429 or response.status_code >= 500:
            log.warning("ESPN returned %s, retrying", response.status_code)
            raise _TransientError(f"ESPN returned HTTP {response.status_code}")
        return response

    @staticmethod
    def _parse(response: httpx.Response, what: str) -> Any:
        status = response.status_code
        if status in (401, 403):
            raise EspnAuthError(
                f"ESPN denied access to {what} (HTTP {status}). For private leagues, set "
                "FGM_ESPN_S2 and FGM_ESPN_SWID; if already set, the cookies have expired."
            )
        if status == 404:
            raise EspnNotFoundError(f"ESPN has no {what}. Check the league id and season.")
        if 300 <= status < 400:
            raise EspnAuthError(f"ESPN redirected the request for {what} (likely to a login page).")
        if status >= 400:
            raise EspnError(f"ESPN returned HTTP {status} for {what}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as e:
            raise EspnAuthError(
                f"ESPN returned non-JSON for {what} (usually a login page: cookies expired)."
            ) from e
