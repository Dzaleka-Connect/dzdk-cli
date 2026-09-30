"""Presentation helpers shared by the CLI (Rich) and the TUI (Textual).

Detail views are produced as Markdown so the same text renders in both
`rich.markdown.Markdown` and `textual.widgets.Markdown`.

Layout of every detail view:

    # Title
    *Category · status · updated 2026-02-05*        <- one muted meta line
    Description paragraph.
    - **Label:** value                               <- facts as a short list
    ## Contact / ## Location / ...                   <- optional sections
    ---
    [services.dzaleka.com/...](...) · `id`
"""
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from dzdk.catalog import Collection, Column, get_path, title_of

NA = "—"
WIKI_LINK_PREFIX = "wiki:"  # Markdown links the TUI intercepts to open another entry

SOCIAL_LABELS = {
    "facebook": "Facebook",
    "twitter": "X",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "youtube": "YouTube",
    "tiktok": "TikTok",
}


def parse_date(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    for candidate in (value.replace("Z", "+00:00"), value):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fmt_date(value: Any, with_time: bool = False) -> str:
    parsed = parse_date(value)
    if not parsed:
        return str(value) if value else NA
    if with_time and (parsed.hour or parsed.minute):
        return parsed.strftime("%Y-%m-%d %H:%M")
    return parsed.strftime("%Y-%m-%d")


def clean_email(value: str) -> str:
    return value.replace("📧", "").strip()


def tel_digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit() or ch == "+")


def domain(url: str) -> str:
    match = re.search(r"https?://([^/]+)", url)
    return (match.group(1) if match else url).replace("www.", "")


def short_url(url: str) -> str:
    """services.dzaleka.com/jobs/x instead of https://services.dzaleka.com/jobs/x"""
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


def present(value: Any) -> bool:
    return value not in (None, "", "N/A", [], {})


def cell_text(item: Dict[str, Any], column: Column) -> str:
    value = get_path(item, column.path)
    if column.kind == "date":
        return fmt_date(value) if value else NA
    if column.kind == "datetime":
        return fmt_date(value, with_time=True) if value else NA
    if column.kind == "list" or isinstance(value, list):
        return ", ".join(map(str, value)) if value else NA
    if column.path == "contact.email" and value:
        return clean_email(str(value))
    if not present(value):
        return NA
    return str(value).strip()


STATUS_TONE = {
    "active": "good", "open": "good", "upcoming": "good", "ongoing": "good",
    "inactive": "bad", "closed": "bad", "cancelled": "bad",
    "past": "muted", "expired": "muted",
}


def status_tone(status: Any) -> str:
    """good | bad | muted | unknown - the UI maps these to theme colours."""
    return STATUS_TONE.get(str(status or "").lower(), "unknown")


# ---------------------------------------------------------------- markdown


def _facts(rows: Iterable[tuple]) -> str:
    lines = [f"- **{str(k).strip()}:** {str(v).strip()}" for k, v in rows if present(v)]
    return "\n".join(lines) + "\n" if lines else ""


def _section(title: str, lines: List[str]) -> str:
    return f"## {title}\n\n" + "\n".join(lines) + "\n" if lines else ""


def _meta_line(*parts: Any) -> str:
    text = " · ".join(str(p) for p in parts if present(p))
    return f"*{text}*\n" if text else ""


def _contact_lines(contact: Dict[str, Any]) -> List[str]:
    lines = []
    if present(contact.get("email")):
        email = clean_email(contact["email"])
        lines.append(f"- **Email:** [{email}](mailto:{email})")
    if present(contact.get("phone")):
        phone = str(contact["phone"]).strip()
        lines.append(f"- **Phone:** [{phone}](tel:{tel_digits(phone)})")
    if present(contact.get("whatsapp")):
        number = tel_digits(str(contact["whatsapp"])).lstrip("+")
        lines.append(f"- **WhatsApp:** [{contact['whatsapp']}](https://wa.me/{number})")
    if present(contact.get("website")):
        lines.append(f"- **Website:** [{domain(contact['website'])}]({contact['website']})")
    if present(contact.get("hours")):
        lines.append(f"- **Hours:** {contact['hours']}")
    return lines


def _social_lines(social: Dict[str, Any]) -> List[str]:
    lines = []
    if present(social.get("website")):
        lines.append(f"- **Website:** [{domain(social['website'])}]({social['website']})")
    links = [f"[{label}]({social[key]})" for key, label in SOCIAL_LABELS.items()
             if present(social.get(key))]
    if present(social.get("whatsapp")):
        number = tel_digits(str(social["whatsapp"])).lstrip("+")
        links.append(f"[WhatsApp](https://wa.me/{number})")
    if links:
        lines.append("- **Social:** " + " · ".join(links))
    return lines


def item_markdown(collection: Collection, item: Dict[str, Any], site_url: str) -> str:
    renderer = _RENDERERS.get(collection.name, _generic_md)
    meta, body = renderer(item)
    flags = []
    if item.get("featured"):
        flags.append("Featured")
    if "verified" in item:
        flags.append("Verified" if item.get("verified") else "Unverified community listing")
    parts = [f"# {title_of(item)}\n", _meta_line(*meta, *flags)]
    if present(item.get("description")):
        parts.append(f"{item['description']}\n")
    parts.append(body)
    url = collection.web_url(site_url, item)
    parts.append(f"\n---\n\n[{short_url(url)}]({url})  ·  id {item.get('id', NA)}\n")
    return "\n".join(p for p in parts if p)


def _service_md(item: Dict[str, Any]):
    meta = [item.get("category"), item.get("status"),
            f"updated {fmt_date(item['lastUpdated'])}" if item.get("lastUpdated") else None]
    body = [_section("Contact", _contact_lines(item.get("contact") or {})
                     + _social_lines(item.get("socialMedia") or {}))]
    location = item.get("location") or {}
    if isinstance(location, dict) and location:
        rows = [f"- {x}" for x in (location.get("address"), location.get("city")) if present(x)]
        coords = location.get("coordinates") or {}
        if coords.get("lat") is not None:
            lat, lng = coords["lat"], coords.get("lng")
            osm = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}"
            rows.append(f"- [{lat:.5f}, {lng:.5f}]({osm}) (OpenStreetMap)")
        body.append(_section("Location", rows))
    extra = _facts([("Languages", ", ".join(item.get("languages") or [])),
                    ("Tags", ", ".join(item.get("tags") or []))])
    if extra:
        body.append(_section("More", [extra.rstrip()]))
    return meta, "\n".join(b for b in body if b)


def _event_md(item: Dict[str, Any]):
    meta = [item.get("category"), item.get("status")]
    when = fmt_date(item.get("date"), True) if item.get("date") else None
    if when and item.get("endDate"):
        when += f" → {fmt_date(item['endDate'], True)}"
    body = [_facts([("When", when), ("Where", item.get("location")),
                    ("Organizer", item.get("organizer")),
                    ("Tags", ", ".join(item.get("tags") or []))])]
    reg = item.get("registration") or {}
    if reg:
        lines = [f"- **Required:** {'yes' if reg.get('required') else 'no'}"]
        if present(reg.get("deadline")):
            lines.append(f"- **Deadline:** {fmt_date(reg['deadline'], True)}")
        if present(reg.get("url")):
            lines.append(f"- **Register:** [{short_url(reg['url'])}]({reg['url']})")
        body.append(_section("Registration", lines))
    body.append(_section("Contact", _contact_lines(item.get("contact") or {})))
    return meta, "\n".join(b for b in body if b)


def _job_md(item: Dict[str, Any]):
    meta = [item.get("type"), item.get("category"), item.get("status")]
    body = [_facts([
        ("Organization", item.get("organization")),
        ("Location", item.get("location")),
        ("Posted", fmt_date(item.get("posted")) if item.get("posted") else None),
        ("Deadline", fmt_date(item.get("deadline")) if item.get("deadline") else None),
    ])]
    skills = item.get("skills") or []
    if skills:
        body.append(_section("Skills", [", ".join(skills)]))
    body.append(_section("How to apply", _contact_lines(item.get("contact") or {})))
    return meta, "\n".join(b for b in body if b)


def _news_md(item: Dict[str, Any]):
    meta = [fmt_date(item.get("date")) if item.get("date") else None, item.get("category"),
            f"by {item['author']}" if present(item.get("author")) else None]
    body = [str(item["body"])] if present(item.get("body")) else []
    if item.get("tags"):
        body.append(_facts([("Tags", ", ".join(item["tags"]))]))
    return meta, "\n".join(body)


def _resource_md(item: Dict[str, Any]):
    meta = [item.get("category"), item.get("fileType"), item.get("fileSize")]
    body = [_facts([
        ("Author", item.get("author")),
        ("Published", fmt_date(item.get("date")) if item.get("date") else None),
        ("Updated", fmt_date(item.get("lastUpdated")) if item.get("lastUpdated") else None),
        ("Languages", ", ".join(item.get("languages") or [])),
    ])]
    links = []
    if present(item.get("downloadUrl")):
        links.append(f"- **Download:** [{short_url(item['downloadUrl'])}]({item['downloadUrl']})")
    if present(item.get("resourceUrl")):
        links.append(f"- **Source:** [{short_url(item['resourceUrl'])}]({item['resourceUrl']})")
    body.append(_section("Links", links))
    return meta, "\n".join(b for b in body if b)


def _photo_md(item: Dict[str, Any]):
    photographer = item.get("photographer") or {}
    if isinstance(photographer, str):
        photographer = {"name": photographer}
    meta = [fmt_date(item.get("date")) if item.get("date") else None, item.get("location")]
    body = [_facts([("Photographer", photographer.get("name")),
                    ("Tags", ", ".join(item.get("tags") or []))])]
    if present(photographer.get("bio")):
        body.append(f"> {photographer['bio']}\n")
    image = item.get("image") or item.get("url")
    if present(image):
        body.append(f"[Open image]({image})\n")
    return meta, "\n".join(b for b in body if b)


def _generic_md(item: Dict[str, Any]):
    skip = {"id", "title", "name", "description", "collection", "featured", "category"}
    rows = []
    for key, value in item.items():
        if key in skip or not present(value):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) if not isinstance(v, dict) else title_of(v) for v in value)
        elif isinstance(value, dict):
            value = ", ".join(f"{k}: {v}" for k, v in value.items() if present(v))
        elif key.lower().endswith(("date", "at", "updated", "posted", "deadline")):
            value = fmt_date(value)
        rows.append((re.sub(r"(?<!^)(?=[A-Z])", " ", key).capitalize(), value))
    return [item.get("category")], _facts(rows)


_RENDERERS = {
    "services": _service_md,
    "events": _event_md,
    "jobs": _job_md,
    "news": _news_md,
    "resources": _resource_md,
    "photos": _photo_md,
}


def entry_markdown(entry: Dict[str, Any], *, wiki_links: bool = False) -> str:
    """Render an encyclopedia entry. With wiki_links, related entries link to `wiki:<slug>`."""
    status = entry.get("status")
    parts = [
        f"# {entry.get('title', 'Untitled')}\n",
        _meta_line(entry.get("category"), entry.get("entryType"),
                   "reviewed" if status == "reviewed" else status,
                   f"last reviewed {fmt_date(entry['lastReviewed'])}" if entry.get("lastReviewed") else None),
    ]
    if entry.get("aliases"):
        parts.append(f"Also known as {', '.join(entry['aliases'])}.\n")
    if entry.get("summary"):
        parts.append(f"> {entry['summary']}\n")
    facts = entry.get("facts") or []
    if facts:
        parts.append(_facts((f.get("label", ""), f.get("value", "")) for f in facts))
    if entry.get("body"):
        parts.append(str(entry["body"]).strip() + "\n")
    related = entry.get("relatedEntries") or []
    if related:
        links = []
        for slug in related:
            label = slug.replace("-", " ").capitalize()
            href = (f"{WIKI_LINK_PREFIX}{slug}" if wiki_links
                    else f"https://services.dzaleka.com/encyclopedia/{slug}")
            links.append(f"[{label}]({href})")
        parts.append(_section("See also", [" · ".join(links)]))
    sources = entry.get("sources") or []
    if sources:
        lines = []
        for i, src in enumerate(sources, 1):
            title = src.get("title", "Source")
            text = f"[{title}]({src['url']})" if src.get("url") else title
            extra = ", ".join(str(x) for x in (src.get("publisher"), src.get("date")) if x)
            lines.append(f"{i}. {text}" + (f", {extra}" if extra else ""))
        parts.append(_section("Sources", lines))
    url = entry.get("url", "")
    parts.append(f"\n---\n\n[{short_url(url)}]({url}) · Dzaleka Encyclopedia, CC BY-SA 4.0\n")
    return "\n".join(p for p in parts if p)


def bar(value: float, maximum: float, width: int = 30) -> str:
    """Horizontal bar using eighth blocks for smooth ends."""
    if maximum <= 0 or value <= 0:
        return ""
    eighths = round(value / maximum * width * 8)
    full, rest = divmod(eighths, 8)
    return "█" * full + (" ▏▎▍▌▋▊▉"[rest] if rest else "")
