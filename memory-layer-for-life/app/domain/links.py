"""Links the user saves for the assistant to share for them (ADR-050): a resume on Google
Drive, a portfolio, a LinkedIn or GitHub profile. No database, no model.

A link is shared as it is, by its address: the assistant puts it in an email or a message
when it helps, such as the resume link in a job application. Nothing is fetched from it.
"""

import re
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from app.domain.documents import looks_like_resume
from app.domain.enums import LinkKind
from app.domain.errors import InvalidLinkError
from app.domain.memory_policy import clean_title

URL_MAX_CHARS: Final = 2000
TITLE_MAX_CHARS: Final = 120

_SCHEME: Final = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOST: Final = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$|^localhost$", re.I)

# Hosts whose links are profiles of a known kind.
_KIND_BY_HOST: Final = {
    "linkedin.com": LinkKind.LINKEDIN,
    "github.com": LinkKind.GITHUB,
    "behance.net": LinkKind.PORTFOLIO,
    "dribbble.com": LinkKind.PORTFOLIO,
}

_HOST_NAMES: Final = {
    "drive.google.com": "Google Drive",
    "docs.google.com": "Google Docs",
    "dropbox.com": "Dropbox",
    "onedrive.live.com": "OneDrive",
    "1drv.ms": "OneDrive",
    "notion.so": "Notion",
    "linkedin.com": "LinkedIn",
    "github.com": "GitHub",
}


def normalize_url(raw: str) -> str:
    """A web address fit to share: ``https://`` added when no scheme was typed, the host
    in lower case, no fragment-only noise. Raises InvalidLinkError when it is not a web
    address."""
    text = raw.strip()
    if not text:
        raise InvalidLinkError("Enter a link.")
    if any(character.isspace() for character in text):
        raise InvalidLinkError("A link cannot contain spaces.")
    if not _SCHEME.match(text):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidLinkError("Only web links (http or https) can be saved.")
    host = (parts.hostname or "").lower()
    if not _HOST.match(host):
        raise InvalidLinkError("That does not look like a web address.")
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    url = urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))
    if len(url) > URL_MAX_CHARS:
        raise InvalidLinkError(f"Links can be at most {URL_MAX_CHARS} characters.")
    return url


def site_of(url: str) -> str:
    """The host without ``www.``, as people name a site."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def guess_kind(url: str, title: str | None) -> LinkKind:
    """What a link most likely is, from its title and its site."""
    if title and looks_like_resume(title, ""):
        return LinkKind.RESUME
    site = site_of(url)
    for host, kind in _KIND_BY_HOST.items():
        if site == host or site.endswith("." + host):
            return kind
    return LinkKind.OTHER


def default_title(url: str, kind: LinkKind) -> str:
    """A title for a link saved without one: what it is, and where."""
    site = site_of(url)
    place = _HOST_NAMES.get(site, site)
    if kind is LinkKind.RESUME:
        return f"Resume ({place})"
    if kind in (LinkKind.LINKEDIN, LinkKind.GITHUB):
        return place
    return clean_title(place, max_chars=TITLE_MAX_CHARS) or "Link"


def clean_link_title(title: str) -> str:
    cleaned = clean_title(title, max_chars=TITLE_MAX_CHARS)
    if not cleaned:
        raise InvalidLinkError("Enter a title.")
    return cleaned
