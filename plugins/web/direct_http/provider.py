"""Direct HTTP content extraction provider — bundled, no API key.

This is the zero-credit native extraction lane for public HTTP(S) pages.
It intentionally supports extraction only; discovery/ranking still belongs to
search backends such as SearXNG or DDGS.
"""

from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


class _VisibleTextParser(HTMLParser):
    """Small stdlib HTML-to-text extractor for direct HTTP fallback use."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}
    _BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
        "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self._title_parts: List[str] = []
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._title_depth:
            self._title_parts.append(text)
        else:
            self._parts.append(text)
            self._parts.append(" ")

    @property
    def title(self) -> str:
        return _normalize_ws(" ".join(self._title_parts))

    @property
    def text(self) -> str:
        lines = [_normalize_ws(line) for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)


def _normalize_ws(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(value or "")).strip()


def _decode_response(response: Any) -> str:
    ctype = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
    charset = ""
    m = re.search(r"charset=([^;]+)", ctype, re.I)
    if m:
        charset = m.group(1).strip().strip('"')
    raw = response.content
    for enc in [charset, getattr(response, "encoding", None), "utf-8", "latin-1"]:
        if not enc:
            continue
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_visible_text(body: str, *, content_type: str = "") -> tuple[str, str]:
    if "html" not in (content_type or "").lower() and not re.search(r"<html|<body|<title", body, re.I):
        return "", _normalize_plain_text(body)
    parser = _VisibleTextParser()
    parser.feed(body)
    parser.close()
    return parser.title, parser.text


def _normalize_plain_text(body: str) -> str:
    lines = [_normalize_ws(line) for line in body.splitlines()]
    return "\n".join(line for line in lines if line)


class DirectHTTPExtractProvider(WebSearchProvider):
    """Zero-credit direct HTTP extractor for public pages."""

    @property
    def name(self) -> str:
        return "direct-http"

    @property
    def display_name(self) -> str:
        return "Direct HTTP"

    def is_available(self) -> bool:
        # Uses bundled httpx dependency and public HTTP(S); no key required.
        return True

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        import httpx

        max_chars = int(kwargs.get("max_chars") or 200_000)
        headers = {
            "User-Agent": "HermesAgent-DirectHTTPExtract/1.0 (+https://hermes-agent.nousresearch.com/docs)",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/xml;q=0.9,*/*;q=0.8",
        }
        results: List[Dict[str, Any]] = []
        with httpx.Client(headers=headers, follow_redirects=True, timeout=30) as client:
            for url in urls:
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    body = _decode_response(response)
                    title, text = _extract_visible_text(body, content_type=content_type)
                    if max_chars and len(text) > max_chars:
                        text = text[:max_chars] + "\n\n[... truncated by direct-http extractor ...]"
                    final_url = str(response.url)
                    results.append(
                        {
                            "url": final_url,
                            "title": title,
                            "content": text,
                            "raw_content": text,
                            "metadata": {
                                "sourceURL": final_url,
                                "title": title,
                                "contentType": content_type,
                                "statusCode": response.status_code,
                                "backend": self.name,
                            },
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — per-URL failure should not abort batch
                    logger.warning("Direct HTTP extraction failed for %s: %s", url, exc)
                    results.append(
                        {
                            "url": url,
                            "title": "",
                            "content": "",
                            "raw_content": "",
                            "error": f"direct-http extraction failed: {exc}",
                            "metadata": {"sourceURL": url, "backend": self.name},
                        }
                    )
        return results

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": self.display_name,
            "badge": "free",
            "tag": "No API key; fetches public HTTP(S) pages directly. Best as web.extract_backend.",
            "env_vars": [],
        }
