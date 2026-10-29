"""Fetch the scan behind an Open Archieven record (or a viewer URL) at full resolution.

Per archive system:
- Memorix (RAT, BHIC, SALHA and others): the record's thumbnail URL holds tenant and image id, and
  download-images.memorix.nl serves the full image directly. RAT goes through the RAT brake in rat.py.
- Mais Internet (archieven.nl for Roermond, RHCL, Rotterdam and others; Het Utrechts Archief on its
  own site): the signed thumbnail URLs in the viewer's film strip are only known to the JavaScript
  viewer, so a headless browser opens it; the thumbnail URL with format=download gives the full
  image. Where that fails, the viewer's Zoomify path is caught from its tile requests and the image
  comes from the IIPImage server, tile by tile at full size.
- anything else: the browser opens the page and keeps the largest image it loads, or a screenshot.

Next to each scan a .json file records where it came from, for the citation.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import math
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lineage import archive, rat, settings, web
from lineage.i18n import t

MEMORIX = re.compile(
    r"images\.memorix\.nl/(?P<tenant>[\w-]+)/(?:thumb/[^/]+|download/\w+)/(?P<id>[0-9a-f-]{36})"
)
MEMORIX_DOWNLOAD = "https://download-images.memorix.nl/{tenant}/download/fullsize/{id}.jpg"
# Archives that switch off full downloads (Breda) still serve this fixed thumbnail size.
MEMORIX_LARGE = "https://images.memorix.nl/{tenant}/thumb/2000x2000/{id}.jpg"
PROXY_DOWNLOAD = re.compile(r"^https?://proxy\.archieven\.nl/download/\d+/[0-9A-F]+$", re.I)
# A scan, not an icon or a preview: the longest side in pixels.
MIN_SIDE = 1500
ZOOMIFY = re.compile(r"^(?P<server>https?://[^?]+iipsrv\.fcgi)\?Zoomify=(?P<fif>.+?\.jp2)/", re.I)
REF = re.compile(r"^[a-z]{2,4}:[\w-]+$")
MAIS_THUMB = re.compile(r"[?&]format=thumb&(?=.*\bmiahd=)", re.I)
MAIS_SELECTED = "() => document.querySelector('.mi_stripthumb.selected img')?.src || null"
MAIS_THUMBNAILS = r"""() => [...document.querySelectorAll("img")].map(i =>
    decodeURIComponent(new URL(i.src, location.href).pathname).split("/").pop().replace(/\.[^.]+$/, ""))"""
MAIS_STRIP = r"""() => [...document.querySelectorAll("img.mi_stripthumb_img")].map(i =>
    decodeURIComponent(new URL(i.src, location.href).pathname).split("/").pop().replace(/\.[^.]+$/, ""))"""
MAIS_POSITION = "() => document.querySelector('.sslider')?.style.marginLeft || null"
# The strip holds the whole inventory but only renders thumbnails near the record; a step is a few.
MAX_PAGING = 150
TILE_GROUP = 256
CONCURRENCY = 4
MAX_SET = 40


IMAGE_SIGNATURES = {
    "jpeg": b"\xff\xd8",
    "png": b"\x89PNG\r\n\x1a\n",
    "tiff": (b"II*\x00", b"MM\x00*"),
    "pdf": b"%PDF",
}
EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "tiff": ".tif", "pdf": ".pdf"}


def image_kind(data: bytes) -> str | None:
    for kind, signature in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return kind
    return None


def require_image(
    data: bytes, source: str, kinds: tuple[str, ...] = ("jpeg", "png", "tiff")
) -> str:
    """The kind of image in data; an archive that is offline answers with an HTML page and status 200."""
    kind = image_kind(data)
    if kind not in kinds:
        raise ScanError(
            t("not an image (site offline?): {source}: {start!r}", source=source, start=data[:60])
        )
    return kind


class ScanError(RuntimeError):
    pass


@dataclass
class Provenance:
    ref: str
    source_url: str
    method: str
    fetched: str
    institution: str = ""
    location: str = ""
    record_url: str = ""
    width: int = 0
    height: int = 0
    remark: str = ""


@dataclass
class Scan:
    viewer: str
    preview: str = ""
    download: str = ""


@dataclass
class Record:
    ref: str
    institution: str = ""
    location: str = ""
    record_url: str = ""
    original: str = ""
    scans: list[Scan] = field(default_factory=list)


def record(ref: str) -> Record:
    archive_code, _, identifier = ref.partition(":")
    data = archive._get("show", {"archive": archive_code, "identifier": identifier, "lang": "nl"})
    if "Source" not in data:
        raise ScanError(t("record {ref} not found at Open Archieven", ref=ref))
    source = data["Source"]
    reference = source.get("SourceReference", {})
    parts = [
        t("archive {number}", number=reference["Archive"]) if reference.get("Archive") else "",
        t("inv. {inventory}", inventory=reference["RegistryNumber"])
        if reference.get("RegistryNumber")
        else "",
        t("record {deed}", deed=reference["DocumentNumber"])
        if reference.get("DocumentNumber")
        else "",
        str(reference.get("Book") or ""),
    ]
    scans = [
        Scan(
            viewer=s.get("UriViewer") or s.get("Uri", ""),
            preview=s.get("UriPreview", ""),
            download=s.get("Uri", ""),
        )
        for s in archive._as_list((source.get("SourceAvailableScans") or {}).get("Scan"))
    ]
    return Record(
        ref=ref,
        institution=reference.get("InstitutionName", ""),
        location=", ".join(p for p in parts if p),
        record_url=archive.RECORD_URL.format(archive=archive_code, identifier=identifier),
        original=str(source.get("SourceDigitalOriginal") or ""),
        scans=scans,
    )


def memorix(url: str) -> tuple[str, str] | None:
    m = MEMORIX.search(url)
    return (m["tenant"], m["id"]) if m else None


def zoomify(url: str) -> tuple[str, str] | None:
    """Server and (still URL-encoded) image path from a Zoomify tile or properties request."""
    m = ZOOMIFY.match(url)
    return (m["server"], m["fif"]) if m else None


def mais_download(thumb: str) -> str | None:
    """The full-size URL of a Mais Internet strip thumbnail; it only works with the signed parameters
    (miahd, open, ...) of the thumbnail, otherwise the server answers with an SVG error image."""
    return (
        MAIS_THUMB.sub(lambda m: m[0].replace("thumb", "download"), thumb, 1)
        if MAIS_THUMB.search(thumb)
        else None
    )


def file_name(preview: str) -> str:
    """The image name in an archieven.nl preview URL (…&file=3797\\Name_1404.jpg), without extension."""
    path = urllib.parse.parse_qs(urllib.parse.urlsplit(preview).query).get("file", [""])[0]
    return Path(path.replace("\\", "/")).stem


def levels(width: int, height: int, tile: int) -> list[tuple[int, int]]:
    """Zoomify levels from the smallest (fits in one tile) to the full size."""
    result = [(width, height)]
    while width > tile or height > tile:
        width, height = math.ceil(width / 2), math.ceil(height / 2)
        result.append((width, height))
    return result[::-1]


def tiles(server: str, fif: str, width: int, height: int, tile: int) -> list[tuple[int, int, str]]:
    """(x, y, url) of every tile at full size; the tile group counts tiles over all smaller levels."""
    all_levels = levels(width, height, tile)
    before = sum(math.ceil(w / tile) * math.ceil(h / tile) for w, h in all_levels[:-1])
    level = len(all_levels) - 1
    columns, rows = math.ceil(width / tile), math.ceil(height / tile)
    result = []
    for y in range(rows):
        for x in range(columns):
            group = (before + y * columns + x) // TILE_GROUP
            result.append((x, y, f"{server}?Zoomify={fif}/TileGroup{group}/{level}-{x}-{y}.jpg"))
    return result


def _properties(server: str, fif: str) -> tuple[int, int, int]:
    xml = web.fetch(f"{server}?Zoomify={fif}/ImageProperties.xml").decode("utf-8", "replace")
    values = dict(re.findall(r'(\w+)="(\d+)"', xml))
    try:
        return int(values["WIDTH"]), int(values["HEIGHT"]), int(values.get("TILESIZE", 256))
    except KeyError as exc:
        raise ScanError(
            t("no image properties from {server}: {start}", server=server, start=xml[:200])
        ) from exc


def _tile(url: str):
    """The server sometimes answers a tile with a placeholder while it is still rendering: retry."""
    from PIL import Image, UnidentifiedImageError

    for attempt in range(4):
        data = web.fetch(url, pause=0.05)
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except UnidentifiedImageError:
            if attempt == 3:
                raise ScanError(
                    t("tile is not an image after four attempts: {url}", url=url)
                ) from None
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def _stitch(server: str, fif: str) -> tuple[bytes, int, int]:
    from PIL import Image

    width, height, tile_size = _properties(server, fif)
    grid = tiles(server, fif, width, height, tile_size)
    image = Image.new("RGB", (width, height), "white")
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        for x, y, tile in pool.map(lambda t: (t[0], t[1], _tile(t[2])), grid):
            image.paste(tile, (x * tile_size, y * tile_size))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue(), width, height


def _page_to(p, name: str) -> int:
    """Index among the page's images of the strip thumbnail with this name, paging the strip if needed."""
    for _ in range(MAX_PAGING):
        names = p.evaluate(MAIS_THUMBNAILS)
        if name in names:
            return names.index(name)
        strip = sorted(p.evaluate(MAIS_STRIP))
        button = p.locator(".snext a" if strip and name > strip[-1] else ".sprev a").first
        position = p.evaluate(MAIS_POSITION)
        if not strip or not button.count():
            break
        button.click()
        p.wait_for_timeout(600)
        p.wait_for_load_state("networkidle")
        if p.evaluate(MAIS_POSITION) == position:
            break
    return -1


def _archieven_fif(viewer: str, name: str, download: bool = True) -> tuple[str, str] | bytes | str:
    """Open the archieven.nl viewer and find the thumbnail of this image: its format=download URL, or
    after a click on it the Zoomify path. Some images are shown without Zoomify; then the largest image
    the viewer loaded is returned."""
    from lineage.browser import page

    found: list[str] = []
    images: list[bytes] = []

    def keep(response) -> None:
        if "image" in (response.headers.get("content-type") or "") and response.ok:
            with contextlib.suppress(Exception):
                images.append(response.body())

    with page() as p:
        p.on("request", lambda r: found.append(r.url) if "Zoomify=" in r.url else None)
        p.goto(viewer, wait_until="networkidle", timeout=90_000)
        index = _page_to(p, name) if name else -1
        if index < 0:
            raise ScanError(
                t("thumbnail {name!r} not found in the viewer {viewer}", name=name, viewer=viewer)
            )
        if download and (full := mais_download(p.locator("img").nth(index).evaluate("i => i.src"))):
            return full
        images.clear()
        p.on("response", keep)
        p.locator("img").nth(index).dispatch_event("click")
        for _ in range(30):
            if found:
                break
            p.wait_for_timeout(500)
        p.wait_for_timeout(1000)
    for url in found:
        if match := zoomify(url):
            return match
    if largest := _largest_scan(images):
        return largest
    raise ScanError(t("the viewer loaded no scan for {name!r}", name=name))


def _half(server: str, fif: str) -> bytes:
    """One request for the whole image; the server caps it (archieven.nl: half the full width)."""
    width, _, _ = _properties(server, fif)
    data = web.fetch(f"{server}?FIF={fif}&WID={width}&QLT=90&CVT=jpeg", timeout=120)
    require_image(data, f"{server} for {fif}", ("jpeg",))
    return data


def _download(url: str) -> bytes:
    data = web.fetch(url, timeout=180)
    require_image(data, url)
    return data


def _archieven(viewer: str, name: str) -> tuple[bytes, str]:
    found = _archieven_fif(viewer, name)
    if isinstance(found, str):
        try:
            return _download(found), "archieven.nl viewer + format=download"
        except (ScanError, web.WebError):
            found = _archieven_fif(viewer, name, download=False)
    if isinstance(found, bytes):
        return found, "archieven.nl viewer (image without zoom)"
    try:
        data, _, _ = _stitch(*found)
        return data, "archieven.nl viewer + zoomify"
    except ScanError:
        return _half(*found), "archieven.nl viewer + zoomify (downscaled: tiles incomplete)"


def _archieven_set(url: str, maximum: int) -> tuple[list[tuple[str, str, str, str]], bool]:
    """All scans on an archieven.nl record page (e.g. a notarial protocol): click every thumbnail and
    catch its Zoomify path. Returns (name, format=download URL, server, fif) per scan and whether
    the page holds more."""
    from lineage.browser import page

    seen: list[str] = []
    result: list[tuple[str, str, str, str]] = []
    with page() as p:
        p.on("request", lambda r: seen.append(r.url) if "Zoomify=" in r.url else None)
        p.goto(url, wait_until="networkidle", timeout=90_000)
        thumbnails = p.locator("img[src*='format=thumb']")
        count = thumbnails.count()
        known: set[str] = set()
        for i in range(min(count, maximum)):
            thumbnail = thumbnails.nth(i)
            src = thumbnail.evaluate("i => i.src")
            name = Path(urllib.parse.urlsplit(src).path).stem
            seen.clear()
            # After the first one the viewer overlay covers the strip.
            thumbnail.dispatch_event("click")
            for _ in range(30):
                fresh = [z for u in seen if (z := zoomify(u)) and z[1] not in known]
                if fresh:
                    known.add(fresh[0][1])
                    result.append((name, mais_download(src) or "", *fresh[0]))
                    break
                p.wait_for_timeout(500)
        more = count > maximum or p.locator("text=Volgende").count() > 0
    if not result:
        raise ScanError(t("no scans found on {url}", url=url))
    return result, more


def _largest_image(url: str, screenshot: bool = True) -> tuple[bytes, str]:
    from lineage.browser import page

    images: list[bytes] = []

    def keep(response) -> None:
        if "image" in (response.headers.get("content-type") or "") and response.ok:
            with contextlib.suppress(Exception):  # a response can vanish when the page navigates
                images.append(response.body())

    with page() as p:
        p.on("response", keep)
        p.goto(url, wait_until="networkidle", timeout=90_000)
        p.wait_for_timeout(3000)
        download = mais_download(p.evaluate(MAIS_SELECTED) or "")
        if not download:
            if largest := _largest_scan(images):
                return largest, "browser: largest image"
            if not screenshot:
                raise ScanError(t("no scan on {url}", url=url))
            return p.screenshot(full_page=True, type="png"), "browser: screenshot"
    data = web.fetch(download, timeout=180)
    require_image(data, download)
    return data, f"mais: selected scan with format=download ({download})"


def _largest_scan(images: list[bytes]) -> bytes | None:
    """The image with the most pixels, if it is large enough to be a scan."""
    sizes = [
        (w * h, data) for data in images for w, h in [_dimensions(data)] if max(w, h) >= MIN_SIDE
    ]
    return max(sizes, key=lambda m: m[0])[1] if sizes else None


def _dimensions(data: bytes) -> tuple[int, int]:
    from PIL import Image

    try:
        return Image.open(io.BytesIO(data)).size
    except Exception:  # noqa: BLE001 - size is informative only
        return 0, 0


def _write(directory: Path, name: str, data: bytes, provenance: Provenance) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = (
        directory / f"{name}{EXTENSIONS[require_image(data, name, ('jpeg', 'png', 'tiff', 'pdf'))]}"
    )
    path.write_bytes(data)
    provenance.width, provenance.height = _dimensions(data)
    path.with_suffix(".json").write_text(
        json.dumps(asdict(provenance), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return path


def _safe(text: str) -> str:
    return re.sub(r"[^\w.-]+", "-", text).strip("-")[:80]


def url_name(url: str) -> str:
    """A file name per URL: host, last path part and the query, since resolvers differ only there."""
    parts = urllib.parse.urlsplit(url)
    return _safe("-".join(d for d in (parts.netloc, Path(parts.path).stem, parts.query) if d))


def _memorix(tenant: str, id_: str) -> tuple[bytes, str]:
    download = MEMORIX_DOWNLOAD.format(tenant=tenant, id=id_)
    if tenant == "tlb":
        data = rat._fetch(download, 120)
        require_image(data, download)
        return data, "memorix tlb"
    try:
        data = web.fetch(download, timeout=180)
        require_image(data, download)
        return data, f"memorix {tenant}"
    except web.WebError as exc:
        if exc.status != 404:
            raise
    large = MEMORIX_LARGE.format(tenant=tenant, id=id_)
    data = web.fetch(large)
    require_image(data, large)
    return data, f"memorix {tenant} (2000 px, no download)"


def _fetch_one(url: str, preview: str = "", download: str = "") -> tuple[bytes, str]:
    if match := memorix(preview or url) or memorix(url) or memorix(download):
        return _memorix(*match)
    if PROXY_DOWNLOAD.match(download or url):
        data = web.fetch(download or url, timeout=180)
        if image_kind(data) in ("jpeg", "png"):
            return data, "archieven.nl download"
    if match := zoomify(url):
        data, _, _ = _stitch(*match)
        return data, "zoomify"
    if "archieven.nl" in url and preview:
        return _archieven(url, file_name(preview))
    return _largest_image(url)


def _fetch_set(rec: Record, directory: Path, today: str, maximum: int) -> list[Path]:
    scans, more = _archieven_set(rec.original, maximum)
    remark = (
        "all scans on the archieven.nl record page; the index does not say which belong to this record"
        + ("; the page has more than these" if more else "")
    )
    result = []
    for name, download, server, fif in scans:
        try:
            if not download:
                raise ScanError(t("no format=download"))
            data, method = _download(download), "archieven.nl record page + format=download"
        except (ScanError, web.WebError):
            data, method = (
                _half(server, fif),
                "archieven.nl record page + zoomify (downscaled, at most half)",
            )
        provenance = Provenance(
            ref=rec.ref,
            source_url=rec.original,
            method=method,
            fetched=today,
            institution=rec.institution,
            location=rec.location,
            record_url=rec.record_url,
            remark=remark,
        )
        result.append(
            _write(directory, _safe(rec.ref.replace(":", "-") + "-" + name), data, provenance)
        )
    return result


def fetch(ref_or_url: str, directory: Path | None = None, maximum: int = MAX_SET) -> list[Path]:
    directory = directory or settings.current().path("scans")
    today = dt.date.today().isoformat()
    if REF.match(ref_or_url):
        rec = record(ref_or_url)
        if not rec.scans and ("archieven.nl" in rec.original or "mivast=" in rec.original):
            return _fetch_set(rec, directory, today, maximum)
        if not rec.scans and rec.original:
            data, method = _largest_image(rec.original, screenshot=False)
            provenance = Provenance(
                ref=ref_or_url,
                source_url=rec.original,
                method=method,
                fetched=today,
                institution=rec.institution,
                location=rec.location,
                record_url=rec.record_url,
                remark="Open Archieven lists no scan; "
                + (
                    "the scan the record page marks for this record"
                    if method.startswith("mais")
                    else "largest image on the source page"
                ),
            )
            return [_write(directory, _safe(ref_or_url.replace(":", "-")), data, provenance)]
        if not rec.scans:
            raise ScanError(
                t(
                    "{ref}: Open Archieven has no scan for this record ({url})",
                    ref=ref_or_url,
                    url=rec.record_url,
                )
            )
        result, errors = [], []
        for i, scan in enumerate(rec.scans, 1):
            try:
                data, method = _fetch_one(scan.viewer, scan.preview, scan.download)
            except (ScanError, web.WebError) as exc:
                errors.append(t("scan {number}: {error}", number=i, error=exc))
                continue
            name = _safe(ref_or_url.replace(":", "-")) + (f"-{i}" if len(rec.scans) > 1 else "")
            provenance = Provenance(
                ref=ref_or_url,
                source_url=scan.viewer,
                method=method,
                fetched=today,
                institution=rec.institution,
                location=rec.location,
                record_url=rec.record_url,
            )
            result.append(_write(directory, name, data, provenance))
        if errors and not result:
            raise ScanError(f"{ref_or_url}: " + "; ".join(errors))
        for error in errors:
            print(f"{ref_or_url}: {error}", file=sys.stderr)
        return result
    data, method = _fetch_one(ref_or_url)
    name = url_name(ref_or_url)
    return [
        _write(
            directory,
            name,
            data,
            Provenance(source_url=ref_or_url, ref=ref_or_url, method=method, fetched=today),
        )
    ]
