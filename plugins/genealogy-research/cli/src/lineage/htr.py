"""Handwritten text recognition through the Transkribus processing API, for hands the helper agents cannot read.

Credentials live outside the repository, in ~/.config/lineage/transkribus.env (or the file in
LINEAGE_TRANSKRIBUS_CONFIG). Every recognised image costs credits on the user's subscription, so a scan that
already has a transcription is never sent again, and one call sends at most a fixed number of new scans.
The output is machine reading: a hit must be read on the scan itself before it counts.
"""

from __future__ import annotations

import base64
import collections
import datetime as dt
import io
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lineage import credentials
from lineage.i18n import t

TOKEN_URL = "https://account.readcoop.eu/auth/realms/readcoop/protocol/openid-connect/token"
API = "https://api-staging.transkribus.org"
CLIENT_ID = "processing-api-client"
# The processing API has no balance endpoint; the classic TrpServer accepts the same token.
CREDITS_URL = "https://transkribus.eu/TrpServer/rest/credits"
DUTCHESS_I = 50786
MODELS = {
    "dutchess": DUTCHESS_I,
    "dean": 309753,
    "titan": 579509,
    "notarieel": 40382,
    "zeeuws": 210033,
}
MODEL_HELP = (
    "dutchess=The Dutchess I (default), dean=Dutch Dean, titan=Text Titan II, "
    "notarieel=Notarial 17th Century Super Model_v2, zeeuws=Large Zeeuws 1550-1700, or a model ID"
)
# Without a layout model the API looks for baselines on its own and skips many spreads ("No baselines detected").
UNIVERSAL_LINES = 51962
MAX_IMAGES = 10
MAX_BYTES = 20 * 1024 * 1024
WAIT_TIME = 15 * 60


class HtrError(RuntimeError):
    pass


class _Expired(HtrError):
    pass


class _Timeout(HtrError):
    pass


def config() -> dict[str, str]:
    return credentials.load(
        "transkribus.env",
        "LINEAGE_TRANSKRIBUS_",
        ("LINEAGE_TRANSKRIBUS_USER", "LINEAGE_TRANSKRIBUS_PASSWORD"),
        HtrError,
        renamed={"GEBRUIKER": "USER", "WACHTWOORD": "PASSWORD"},
    )


def _request(
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        error = _Timeout if exc.code == 408 else _Expired if exc.code == 401 else HtrError
        raise error(t("{url}: HTTP {code}: {body}", url=url, code=exc.code, body=body)) from exc
    except urllib.error.URLError as exc:
        raise HtrError(t("{url}: {reason}", url=url, reason=exc.reason)) from exc


def token(cfg: dict[str, str]) -> str:
    form = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": cfg["LINEAGE_TRANSKRIBUS_USER"],
            "password": cfg["LINEAGE_TRANSKRIBUS_PASSWORD"],
        }
    ).encode()
    answer = json.loads(
        _request(TOKEN_URL, form, {"Content-Type": "application/x-www-form-urlencoded"})
    )
    return answer["access_token"]


@dataclass(frozen=True)
class Package:
    label: str
    balance: float
    expires: str


def packages(bearer: str) -> list[Package]:
    """Active recognition credit packages on the account."""
    root = ET.fromstring(_request(CREDITS_URL, headers={"Authorization": f"Bearer {bearer}"}))
    return [
        Package(
            p.findtext("product/label", ""),
            float(p.findtext("balance", "0")),
            p.findtext("expirationDate", "")[:10],
        )
        for p in root.iter("trpCreditPackage")
        if p.findtext("active") == "true"
        and p.findtext("product/creditType", "recognition") == "recognition"
    ]


def balance(bearer: str) -> float:
    return sum(p.balance for p in packages(bearer))


def text(content: dict) -> str:
    """Lines in reading order, a blank line between text regions."""
    blocks = [
        "\n".join(line.get("text", "") for line in region.get("lines", []))
        for region in content.get("regions", [])
    ]
    blocks = [b for b in blocks if b.strip()]
    return "\n\n".join(blocks) if blocks else content.get("text", "")


def model_id(value: str) -> int:
    """A model by short name or number."""
    if value.lower() in MODELS:
        return MODELS[value.lower()]
    if value.isdigit():
        return int(value)
    raise HtrError(
        t("unknown model {value!r}; choose from {models}", value=value, models=MODEL_HELP)
    )


def outputs(image: Path, model: int = DUTCHESS_I) -> tuple[Path, Path]:
    """Output next to the scan; the default model keeps the plain name, any other model gets its own files."""
    directory = image.parent / "htr"
    if model == DUTCHESS_I:
        name = image.stem
    else:
        short = next((k for k, v in MODELS.items() if v == model), str(model))
        name = f"{image.stem}.{short}"
    return directory / f"{name}.txt", directory / f"{name}.xml"


def new_images(images: list[Path], model: int = DUTCHESS_I) -> list[Path]:
    return [b for b in images if not outputs(b, model)[0].exists()]


def log_path() -> Path:
    """One counter for all worktrees of a repository: the common dir, else a cache file."""
    if own := os.environ.get("LINEAGE_HTR_LOG") or os.environ.get("NDYGEN_HTR_LOG"):
        return Path(own)
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(common) / "lineage-htr.log"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.home() / ".cache" / "lineage" / "htr.log"


def _log(image: Path, model: int) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        # Absolute, so `lineage review` can tell which research round (dr-<ID>/ in the path) used the credit.
        f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}\t{model}\t{image.resolve()}\n")


def count(since: dt.date | None = None) -> tuple[int, collections.Counter[int]]:
    """Recognitions in the log (from `since` on), in total and per model."""
    path = log_path()
    per_model: collections.Counter[int] = collections.Counter()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            when, _, rest = line.partition("\t")
            model = rest.partition("\t")[0]
            if model.isdigit() and (since is None or when[:10] >= since.isoformat()):
                per_model[int(model)] += 1
    return per_model.total(), per_model


def recognize(image: Path, model: int, cfg: dict[str, str], bearer: str) -> tuple[Path, Path]:
    data = image.read_bytes()
    if len(data) > MAX_BYTES:
        raise HtrError(t("{image}: larger than 20 MB", image=image))
    api = cfg.get("LINEAGE_TRANSKRIBUS_URL", API).rstrip("/")
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    payload = {
        "config": {
            "lineDetection": {"modelId": UNIVERSAL_LINES},
            "textRecognition": {"htrId": model},
        },
        "image": {"base64": base64.b64encode(data).decode("ascii")},
    }
    job = json.loads(_request(f"{api}/v2/processes", json.dumps(payload).encode(), headers))
    process = job["processId"]
    deadline = time.monotonic() + WAIT_TIME
    while job["status"] not in ("FINISHED", "FAILED", "CANCELLED"):
        if time.monotonic() > deadline:
            raise HtrError(
                t(
                    "{image}: job {process} not finished after {minutes} minutes",
                    image=image,
                    process=process,
                    minutes=WAIT_TIME // 60,
                )
            )
        try:
            job = json.loads(
                _request(
                    f"{api}/v2/processes/longpoll/{process}?interval=5000",
                    headers=headers,
                    timeout=300,
                )
            )
        except _Timeout:
            continue
        except _Expired:
            headers["Authorization"] = f"Bearer {token(cfg)}"
    if job["status"] != "FINISHED":
        raise HtrError(
            t("{image}: job {process} {status}", image=image, process=process, status=job["status"])
        )
    if not (job.get("content") or {}).get("regions"):
        raise HtrError(
            t(
                "{image}: job {process} without text: {reason}",
                image=image,
                process=process,
                reason=_reason(api, process, headers),
            )
        )
    txt, xml = outputs(image, model)
    txt.parent.mkdir(parents=True, exist_ok=True)
    xml.write_bytes(_request(f"{api}/v2/processes/{process}/page", headers=headers))
    txt.write_text(text(job.get("content") or {}), encoding="utf-8")
    _log(image, model)
    return txt, xml


def _reason(api: str, process: int, headers: dict[str, str]) -> str:
    try:
        archive = zipfile.ZipFile(
            io.BytesIO(_request(f"{api}/v2/processes/{process}/result", headers=headers))
        )
        pages = json.loads(archive.read("result.json")).get("pages", [])
    except (HtrError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return "reason unknown"
    return "; ".join(f"{p.get('status')}: {p.get('reason', '')}" for p in pages) or t(
        "reason unknown"
    )
