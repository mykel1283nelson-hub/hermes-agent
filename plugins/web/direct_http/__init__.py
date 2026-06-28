"""Direct HTTP extract plugin — bundled, auto-loaded."""

from __future__ import annotations

from plugins.web.direct_http.provider import DirectHTTPExtractProvider


def register(ctx) -> None:
    """Register the no-key direct HTTP extractor with the plugin context."""
    ctx.register_web_search_provider(DirectHTTPExtractProvider())
