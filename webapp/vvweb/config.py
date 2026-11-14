"""Web app configuration (env-driven).

Reads `VERISCRIPT_*` first; the legacy `VECTOVECTO_*` names still work as a
fallback (see `branding.py`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from veriscript import branding


def _env_int(name: str, default: int) -> int:
    try:
        return int(branding.env(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """All runtime knobs in one place. Env-first; safe defaults."""

    # "demo" (hosted, shared, quotas on) or "local" (one person on their own
    # machine, e.g. inside the desktop app). Only changes what the UI says;
    # limits stay env-driven so each deployment sets them explicitly.
    mode: str = field(default_factory=lambda: (
        "local" if str(branding.env("WEB_MODE", "demo")).strip().lower() == "local"
        else "demo"))

    # Desktop shell: a per-launch secret. When set, every request must carry
    # it (session cookie or X-VeriScript-Token header), so other programs on
    # the machine cannot drive this server. See security.DesktopSessionMiddleware.
    desktop_token: str | None = field(
        default_factory=lambda: branding.env("WEB_DESKTOP_TOKEN") or None)

    # Where run artifacts live (default: webapp/runs). The desktop app points
    # this at the user's app-data folder.
    runs_dir: str | None = field(
        default_factory=lambda: branding.env("WEB_RUNS_DIR") or None)

    host: str = field(default_factory=lambda: branding.env("WEB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("WEB_PORT", 8000))

    # Upload limits
    max_upload_mb: int = field(default_factory=lambda: _env_int("WEB_MAX_UPLOAD_MB", 12))
    max_image_megapixels: int = field(default_factory=lambda: _env_int("WEB_MAX_MP", 30))
    video_upload_mb: int = field(default_factory=lambda: _env_int("WEB_VIDEO_UPLOAD_MB", 512))
    video_max_pages: int = field(default_factory=lambda: _env_int("WEB_VIDEO_MAX_PAGES", 150))
    video_max_seconds: int = field(default_factory=lambda: _env_int("WEB_VIDEO_MAX_SECONDS", 600))
    video_timeout_s: int = field(default_factory=lambda: _env_int("WEB_VIDEO_TIMEOUT_S", 600))
    video_pages_per_client: int = field(default_factory=lambda: _env_int("WEB_VIDEO_PAGES_PER_CLIENT", 200))

    # PDF pages read per run with "all pages" on. 0 = no cap (desktop app).
    page_cap: int = field(default_factory=lambda: max(0, _env_int("WEB_PAGE_CAP", 10)))
    # Jobs waiting behind the one running (the rest get a 503).
    max_queued_jobs: int = field(default_factory=lambda: max(1, _env_int("WEB_MAX_QUEUED", 20)))

    # Processing
    process_timeout_s: int = field(default_factory=lambda: _env_int("WEB_TIMEOUT_S", 180))
    max_concurrent: int = field(default_factory=lambda: _env_int("WEB_CONCURRENCY", 1))

    # Real client IP for rate limiting: "direct" (default) or "xff-last".
    # "xff-last" trusts the last X-Forwarded-For entry — correct for managed
    # edges that append the client IP (Cloud Run; Cloudflare/Caddy with the
    # Caddyfile's client_ip_headers). Never use it with an untrusted proxy.
    client_ip_mode: str = field(default_factory=lambda: branding.env(
        "WEB_CLIENT_IP_MODE", "direct").strip().lower())

    # Transport: uvicorn sheds connections beyond this (slowloris/flood guard).
    max_connections: int = field(default_factory=lambda: _env_int("WEB_MAX_CONNECTIONS", 32))

    # Hard daily run budget across all clients (0 disables). The billing
    # kill-switch: even a distributed flood cannot exceed this many pages/day.
    daily_runs: int = field(default_factory=lambda: _env_int("WEB_DAILY_RUNS", 300))

    # Page accounting (a 10-page PDF costs 10):
    #   per visitor/IP per day — the free-demo limit
    #   global per day — the overall spend ceiling
    pages_per_client: int = field(default_factory=lambda: _env_int(
        "WEB_DAILY_PAGES_PER_CLIENT", 20))
    daily_pages: int = field(default_factory=lambda: _env_int("WEB_DAILY_PAGES", 500))

    # OCR language warmed at startup so the first visitor does not pay the
    # model init / one-time Devanagari download (the UI defaults to Nepali).
    warm_lang: str = field(default_factory=lambda: branding.env("WEB_WARM_LANG", "ne"))

    # Trusted reverse proxy for real client IPs (rate limiting). Uvicorn
    # `proxy_headers` + `forwarded_allow_ips`; empty = off. See docs/DEPLOY.md.
    forwarded_allow_ips: str = field(default_factory=lambda: str(
        branding.env("WEB_FORWARDED_ALLOW_IPS", "")).strip())

    # Retention
    run_ttl_minutes: int = field(default_factory=lambda: _env_int("WEB_TTL_MINUTES", 60))
    prune_interval_s: int = field(default_factory=lambda: _env_int("WEB_PRUNE_S", 600))

    # Rate limiting (per client IP, sliding window)
    rate_window_s: int = field(default_factory=lambda: _env_int("WEB_RATE_WINDOW_S", 120))
    rate_max_in_window: int = field(default_factory=lambda: _env_int("WEB_RATE_MAX", 6))

    # Optional basic auth for the API (set both to enable)
    auth_user: str | None = field(default_factory=lambda: branding.env("WEB_USER") or None)
    auth_password: str | None = field(default_factory=lambda: branding.env("WEB_PASSWORD") or None)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_user and self.auth_password)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def run_ttl_seconds(self) -> int:
        """0 = keep runs until the user deletes them (desktop app)."""
        return max(0, self.run_ttl_minutes) * 60


settings = Settings()
