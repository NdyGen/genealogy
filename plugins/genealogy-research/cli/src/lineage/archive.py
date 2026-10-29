"""Open Archieven (openarchieven.nl) lookups, and GEDCOM citations that point back to the record."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from lineage.i18n import t

API = "https://api.openarch.nl/1.1/records"
RECORD_URL = "https://www.openarchieven.nl/{archive}:{identifier}"
CACHE_DIR = Path.home() / ".cache" / "lineage" / "openarch"
USER_AGENT = "lineage/0.1 (genealogy research)"
# Open Archieven types unclassified registers as "other:<name>"; the prefix is noise in a title.
OTHER_PREFIX = "other:"
PRIMARY_SOURCE_PREFIXES = ("BS ", "DTB ")


class ArchiveError(RuntimeError):
    pass


def _get(endpoint: str, params: dict[str, str | int]) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{API}/{endpoint}.json?{query}"
    cache = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except (OSError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise ArchiveError(t("Open Archieven unreachable: {error}", error=exc)) from exc
            time.sleep(2 * (attempt + 1))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


@dataclass(frozen=True)
class Hit:
    archive: str
    identifier: str
    person: str
    role: str
    event: str
    date: str
    place: str
    source_type: str
    institution: str

    @property
    def ref(self) -> str:
        return f"{self.archive}:{self.identifier}"


def _date_text(date: dict | None) -> str:
    if not date:
        return ""
    parts = [date.get(k) or date.get(k.capitalize()) for k in ("day", "month", "year")]
    return "-".join(str(p) for p in parts if p)


def search(
    name: str,
    event: str = "",
    place: str = "",
    role: str = "",
    source_type: str = "",
    limit: int = 20,
) -> tuple[int, list[Hit]]:
    """`name` accepts Open Archieven syntax: a year range ("Jan Smit 1850-1860") and
    two persons joined by '&' ("Jan Smit & Maria Jansen")."""
    params = {
        "name": name,
        "eventtype": event,
        "eventplace": place,
        "relationtype": role,
        "sourcetype": source_type,
        "number_show": limit,
        "lang": "nl",
    }
    response = _get("search", params)["response"]
    hits = [
        Hit(
            archive=doc.get("archive_code", ""),
            identifier=doc.get("identifier", ""),
            person=doc.get("personname", ""),
            role=doc.get("relationtype", ""),
            event=doc.get("eventtype", ""),
            date=_date_text(doc.get("eventdate")),
            place=", ".join(doc.get("eventplace") or []),
            source_type=doc.get("sourcetype", ""),
            institution=doc.get("archive_org", ""),
        )
        for doc in response.get("docs", [])
    ]
    return int(response.get("number_found", 0)), hits


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _place(value) -> str:
    return value.get("Place", "") if isinstance(value, dict) else str(value or "")


def _name(person: dict) -> str:
    name = person.get("PersonName", {})
    parts = [
        name.get("PersonNameFirstName"),
        name.get("PersonNamePatronym"),
        name.get("PersonNamePrefixLastName"),
        name.get("PersonNameLastName"),
    ]
    return " ".join(p for p in parts if p)


def _age(person: dict) -> str:
    age = person.get("Age") or {}
    if "PersonAgeLiteral" in age:
        return str(age["PersonAgeLiteral"])
    years = age.get("PersonAgeYears")
    return str(years) if years is not None else ""


@dataclass
class RecordPerson:
    role: str
    name: str
    age: str = ""
    birth: str = ""
    residence: str = ""
    profession: str = ""


@dataclass
class Record:
    archive: str
    identifier: str
    source_type: str
    event: str
    date: str
    place: str
    institution: str
    archive_number: str = ""
    inventory: str = ""
    deed: str = ""
    book: str = ""
    scan_url: str = ""
    persons: list[RecordPerson] = field(default_factory=list)
    remarks: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return RECORD_URL.format(archive=self.archive, identifier=self.identifier)

    @property
    def source_title(self) -> str:
        """Raw, "other:" included: the record ID is derived from it and must stay stable."""
        return f"{self.source_type} {self.place}".strip()

    @property
    def source_xref(self) -> str:
        """Deterministic, so parallel edits citing the same register create the same record."""
        key = f"{self.institution}|{self.source_title}".encode()
        return "OA" + hashlib.sha1(key).hexdigest()[:8].upper()

    @property
    def quality(self) -> int:
        return 3 if self.source_type.startswith(PRIMARY_SOURCE_PREFIXES) else 2

    @property
    def page(self) -> str:
        parts = [
            t("record {deed}", deed=self.deed) if self.deed else "",
            self.date,
            t("archive {number}", number=self.archive_number) if self.archive_number else "",
            t("inv. {inventory}", inventory=self.inventory) if self.inventory else "",
        ]
        return ", ".join(p for p in parts if p) + f"; {self.url}"

    def gedcom_source(self) -> str:
        return "\n".join(
            [
                f"0 @{self.source_xref}@ SOUR",
                f"1 TITL {self.source_title.removeprefix(OTHER_PREFIX)}",
                f"1 AUTH {self.institution}",
                "1 PUBL Open Archieven, https://www.openarchieven.nl",
            ]
        )

    def gedcom_citation(self, level: int = 2) -> str:
        return "\n".join(
            [
                f"{level} SOUR @{self.source_xref}@",
                f"{level + 1} PAGE {self.page}",
                f"{level + 1} QUAY {self.quality}",
            ]
        )


def _scan_url(source: dict) -> str:
    scans = _as_list((source.get("SourceAvailableScans") or {}).get("Scan"))
    return scans[0].get("Uri", "") if scans else ""


def _remarks(source: dict, events: list[dict]) -> list[str]:
    result = []
    remarks = _as_list(source.get("SourceRemark"))
    for event in events:
        remarks += _as_list(event.get("EventRemark"))
    for remark in remarks:
        if isinstance(remark, dict):
            if remark.get("@Key") not in ("Provenance", "link_EAD") and remark.get("Value"):
                result.append(f"{remark.get('@Key', '')}: {remark['Value']}".lstrip(": "))
        elif remark:
            result.append(str(remark))
    return result


def show(ref: str) -> Record:
    archive, _, identifier = ref.partition(":")
    if not identifier:
        raise ArchiveError(t("expected <archive>:<identifier>, got {ref!r}", ref=ref))
    data = _get("show", {"archive": archive, "identifier": identifier, "lang": "nl"})
    if "Person" not in data:
        raise ArchiveError(t("record {ref} not found", ref=ref))

    source = data.get("Source", {})
    reference = source.get("SourceReference", {})
    events = _as_list(data.get("Event"))
    event = events[0] if events else {}
    roles = {
        r.get("PersonKeyRef"): r.get("RelationType", "") for r in _as_list(data.get("RelationEP"))
    }

    record = Record(
        archive=archive,
        identifier=identifier,
        source_type=source.get("SourceType", ""),
        event=event.get("EventType", ""),
        date=_date_text(event.get("EventDate") or source.get("SourceDate")),
        place=_place(event.get("EventPlace")) or _place(source.get("SourcePlace")),
        institution=reference.get("InstitutionName", ""),
        archive_number=str(reference.get("Archive", "")),
        inventory=str(reference.get("RegistryNumber", "")),
        deed=str(reference.get("DocumentNumber", "")),
        book=reference.get("Book", ""),
        scan_url=_scan_url(source),
        remarks=_remarks(source, events),
    )
    for person in _as_list(data.get("Person")):
        birth = " ".join(
            p for p in (_date_text(person.get("BirthDate")), _place(person.get("BirthPlace"))) if p
        )
        record.persons.append(
            RecordPerson(
                role=roles.get(person.get("@pid"), ""),
                name=_name(person),
                age=_age(person),
                birth=birth,
                residence=_place(person.get("Residence")),
                profession=str(person.get("Profession") or ""),
            )
        )
    return record


def describe(record: Record) -> str:
    lines = [
        f"{record.source_type} | {record.event} {record.date} | {record.place}",
        t(
            "{institution}, archive {number}, inv. {inventory}, record {deed} ({book})",
            institution=record.institution,
            number=record.archive_number,
            inventory=record.inventory,
            deed=record.deed or "?",
            book=record.book,
        ),
        t("record: {url}", url=record.url),
        t("scan: {url}", url=record.scan_url or t("none")),
    ]
    for person in record.persons:
        details = ", ".join(
            p
            for p in (
                t("{age} y", age=person.age) if person.age else "",
                t("b. {birth}", birth=person.birth) if person.birth else "",
                person.profession,
                t("res. {residence}", residence=person.residence) if person.residence else "",
            )
            if p
        )
        lines.append(
            f"  {person.role or '?'}: {person.name}" + (f" ({details})" if details else "")
        )
    lines += [t("  remark: {remark}", remark=remark) for remark in record.remarks]
    return "\n".join(lines)
