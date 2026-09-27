"""An in-memory Horizon REST server (httpx.MockTransport) for the multi-user tests.

It issues per-user tokens on /rest/login, rotates access tokens on /rest/refresh and
records the Authorization header of every API request, so tests can assert on exactly
which token each request carried.
"""
import asyncio
import itertools
import json

import httpx


class FakeHorizon:
    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.access: dict[str, str] = {}      # valid access token -> AD user
        self.refresh: dict[str, str] = {}     # valid refresh token -> AD user
        self.requests: list[tuple[str, str, str]] = []  # (method, path, Authorization header)
        self.refresh_calls: list[str] = []    # refresh tokens presented to /rest/refresh
        self.logouts: list[str] = []          # refresh tokens presented to /rest/logout
        self.delay = 0.0                      # seconds each API request takes

    def expire(self, user: str) -> None:
        """Invalidate every access token issued to `user` (like Horizon's ~8h expiry)."""
        self.access = {t: u for t, u in self.access.items() if u != user}

    def revoke_refresh(self, user: str) -> None:
        self.refresh = {t: u for t, u in self.refresh.items() if u != user}

    def _issue(self, user: str) -> str:
        token = f"at-{user}-{next(self._n)}-secret"
        self.access[token] = user
        return token

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path == "/rest/login":
            user = body["username"]
            if body.get("password") != f"pw-{user}":
                return httpx.Response(401, json={"error_message": "bad credentials"})
            refresh = f"rt-{user}-{next(self._n)}-secret"
            self.refresh[refresh] = user
            return httpx.Response(200, json={"access_token": self._issue(user), "refresh_token": refresh})
        if path == "/rest/refresh":
            self.refresh_calls.append(body["refresh_token"])
            await asyncio.sleep(0.02)
            user = self.refresh.get(body["refresh_token"])
            if user is None:
                return httpx.Response(400, json={"error_message": "invalid refresh token"})
            return httpx.Response(200, json={"access_token": self._issue(user)})
        if path == "/rest/logout":
            self.logouts.append(body["refresh_token"])
            self.refresh.pop(body["refresh_token"], None)
            auth = request.headers.get("authorization", "").removeprefix("Bearer ")
            self.access.pop(auth, None)
            return httpx.Response(200)

        auth = request.headers.get("authorization", "")
        self.requests.append((request.method, path, auth))
        await asyncio.sleep(self.delay)
        user = self.access.get(auth.removeprefix("Bearer "))
        if user is None:
            return httpx.Response(401, json={"error_message": "token expired or invalid"})
        if request.method == "GET" and path.endswith("/desktop-pools"):
            return httpx.Response(200, json=[{"id": f"pool-of-{user}", "name": f"Pool of {user}"}])
        if request.method == "GET" and "/desktop-pools/" in path:
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1], "name": "Sales"})
        return httpx.Response(204)

    def install(self, monkeypatch) -> "FakeHorizon":
        """Route every Horizon request the server makes (API, login, refresh, logout) here."""
        monkeypatch.setattr("horizon_mcp.client.new_transport", lambda retries=0: httpx.MockTransport(self.handler))
        return self

    def tokens_sent(self) -> list[str]:
        return [auth for _, _, auth in self.requests]
