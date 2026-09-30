"""Registry of API collections and how to display them.

Both the Click commands and the Textual UI read from COLLECTIONS, so adding a
collection here makes it available everywhere.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Column:
    header: str
    path: str  # dotted path into the item, e.g. "photographer.name"
    width: Optional[int] = None
    kind: str = "text"  # text | date | datetime | list | status


@dataclass(frozen=True)
class Collection:
    name: str  # API path segment, e.g. "services"
    label: str
    columns: Tuple[Column, ...]
    search_fields: Tuple[str, ...] = ("title", "description", "category")
    filter_field: Optional[str] = "category"
    sort_fields: Tuple[str, ...] = ("title", "category", "status")
    web_path: Optional[str] = None  # site path for item pages; defaults to name
    primary: bool = True  # gets its own CLI group and TUI tab
    aliases: Tuple[str, ...] = field(default_factory=tuple)

    def web_url(self, site_url: str, item: Dict[str, Any]) -> str:
        if item.get("url") and str(item["url"]).startswith("http"):
            return str(item["url"])
        ident = item.get("id") or item.get("slug") or ""
        return f"{site_url}/{self.web_path or self.name}/{ident}".rstrip("/")


_GENERIC = (
    Column("Title", "title", 40),
    Column("Category", "category", 20),
    Column("Description", "description", 50),
)

COLLECTIONS: Dict[str, Collection] = {c.name: c for c in [
    Collection(
        "services", "Services",
        (
            Column("Name", "title", 30),
            Column("Category", "category", 16),
            Column("Status", "status", 9, "status"),
        ),
        search_fields=("title", "description", "category", "location.address"),
    ),
    Collection(
        "events", "Events",
        (
            Column("Event", "title", 34),
            Column("Date", "date", 10, "date"),
            Column("Status", "status", 9, "status"),
        ),
        search_fields=("title", "description", "category", "location", "organizer"),
        sort_fields=("title", "date", "category", "status"),
    ),
    Collection(
        "jobs", "Jobs",
        (
            Column("Role", "title", 30),
            Column("Organization", "organization", 16),
            Column("Deadline", "deadline", 10, "date"),
        ),
        search_fields=("title", "description", "organization", "category", "location", "skills"),
        sort_fields=("title", "deadline", "posted", "category", "status"),
    ),
    Collection(
        "news", "News",
        (
            Column("Headline", "title", 38),
            Column("Date", "date", 10, "date"),
            Column("Category", "category", 14),
        ),
        search_fields=("title", "description", "category", "author", "tags"),
        sort_fields=("date", "title", "category"),
    ),
    Collection(
        "resources", "Resources",
        (
            Column("Title", "title", 36),
            Column("Category", "category", 14),
            Column("Type", "fileType", 6),
        ),
        search_fields=("title", "description", "category", "author"),
        sort_fields=("title", "category", "date", "author"),
    ),
    Collection(
        "photos", "Photos",
        (
            Column("Title", "title", 32),
            Column("Photographer", "photographer.name", 18),
            Column("Date", "date", 10, "date"),
        ),
        search_fields=("title", "description", "location", "tags", "photographer.name"),
        filter_field=None,
        sort_fields=("title", "date", "location"),
    ),
    # Secondary collections: browsable with `dzdk browse <name>`.
    Collection("courses", "Courses", _GENERIC, primary=False),
    Collection("community-voices", "Community Voices", _GENERIC, primary=False),
    Collection("talents", "Talents", _GENERIC, primary=False),
    Collection("profiles", "Profiles", _GENERIC, primary=False),
    Collection("artists", "Artists", _GENERIC, primary=False),
    Collection("artworks", "Artworks", _GENERIC, primary=False),
    Collection("poets", "Poets", _GENERIC, primary=False),
    Collection("dancers", "Dancers", _GENERIC, primary=False),
    Collection("marketplace", "Marketplace", _GENERIC, primary=False),
    Collection("stores", "Stores", _GENERIC, primary=False),
    Collection("rights", "Rights", _GENERIC, primary=False),
    Collection("docs", "Docs", _GENERIC, primary=False),
]}

PRIMARY = [c for c in COLLECTIONS.values() if c.primary]


def get_path(item: Dict[str, Any], path: str) -> Any:
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def title_of(item: Dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or item.get("id") or "Untitled").strip()


def matches(item: Dict[str, Any], query: str, fields: Tuple[str, ...]) -> bool:
    query = query.lower()
    for path in fields:
        value = get_path(item, path)
        if isinstance(value, list):
            value = " ".join(map(str, value))
        if value and query in str(value).lower():
            return True
    return False


def filter_items(
    items: List[Dict[str, Any]],
    collection: Collection,
    *,
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
) -> List[Dict[str, Any]]:
    result = [i for i in items if isinstance(i, dict)]
    if search:
        result = [i for i in result if matches(i, search, collection.search_fields)]
    if category and collection.filter_field:
        needle = category.lower()
        result = [i for i in result if needle in str(get_path(i, collection.filter_field) or "").lower()]
    if status:
        result = [i for i in result if str(i.get("status", "")).lower() == status.lower()]
    if sort_by:
        result.sort(key=lambda i: str(get_path(i, sort_by) or "").lower(),
                    reverse=sort_order == "desc")
    return result


def categories(items: List[Dict[str, Any]], collection: Collection) -> List[str]:
    if not collection.filter_field:
        return []
    values = {str(get_path(i, collection.filter_field)).strip() for i in items
              if get_path(i, collection.filter_field)}
    return sorted(values, key=str.lower)


def resolve(name: str) -> Optional[Collection]:
    name = name.lower()
    if name in COLLECTIONS:
        return COLLECTIONS[name]
    for c in COLLECTIONS.values():
        if name in c.aliases or name == c.label.lower():
            return c
    return None
