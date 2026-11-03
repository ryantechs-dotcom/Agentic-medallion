#!/usr/bin/env python3
"""
ingest_data.py - Pull every dataset and documentation source for the
ADSP 32018 project into one local folder, verify it, and (optionally)
load it into a single DuckDB file the agents can query.

What it fetches
---------------
1. MIMIC-IV Clinical Database Demo (PhysioNet), v1.0 and v2.2
     v1.0 -> the version the OMOP ETL was written against (has the old `core` module)
     v2.2 -> the current demo; matches the current MIMIC documentation
2. MIMIC-IV Demo in the OMOP CDM v0.9 (PhysioNet)       -> ground truth for mapping
3. OHDSI/MIMIC ETL repo (SQL + custom concept mappings) -> field/concept-level ground truth
4. OMOP CDM v5.3 table & field specifications (OHDSI)   -> RAG corpus
5. MIMIC-IV documentation pages (mimic.mit.edu source)  -> RAG corpus
6. NHANES 2017-2018 data files (.xpt) + codebooks (.htm) -> data + RAG corpus

Output layout
-------------
data/
  raw/
    physionet/<project>_<version>/...   (mirrors PhysioNet's folder structure)
    nhanes/<cycle>/data/*.xpt
    nhanes/<cycle>/docs/*.htm
    github/omop_etl/...
  docs/
    mimic/*.md
    omop/*.csv
    nhanes/*.htm   (copied from raw so the RAG corpus lives in one place)
  project.duckdb   (optional)
  manifest.json    (url, path, size, sha256, status for every file)

Usage
-----
    pip install requests pandas duckdb
    python ingest_data.py                 # everything
    python ingest_data.py --only nhanes   # one source group
    python ingest_data.py --no-duckdb     # download only
    python ingest_data.py --force         # re-download files that already exist

Everything here is openly licensed and needs no login. Cite each source in the
report (PhysioNet pages list the required citations).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuration - edit here, not in the functions below
# ---------------------------------------------------------------------------

PHYSIONET_PROJECTS = [
    # (project slug, version, local folder name)
    ("mimic-iv-demo", "1.0", "mimic_demo_v1_0"),
    ("mimic-iv-demo", "2.2", "mimic_demo_v2_2"),
    ("mimic-iv-demo-omop", "0.9", "omop_demo_v0_9"),
]
PHYSIONET_FILES = "https://physionet.org/files/{slug}/{version}/"
PHYSIONET_S3 = "https://physionet-open.s3.amazonaws.com/"  # anonymous fallback

# NHANES: cycle label -> (folder year used in CDC URLs, file suffix letter)
NHANES_CYCLES = {
    "2017-2018": ("2017", "J"),
    # "2021-2023": ("2021", "L"),   # uncomment to add the newest cycle
}
# Component file prefixes. Not every prefix exists in every cycle
# (e.g. 2021-2023 has BPXO but no BPX); missing ones are logged, not fatal.
NHANES_COMPONENTS = [
    "DEMO",    # demographics
    "BMX",     # body measures
    "BPX",     # blood pressure (auscultation)
    "BPXO",    # blood pressure (oscillometric)
    "GHB",     # glycohemoglobin
    "GLU",     # fasting glucose
    "TCHOL",   # total cholesterol
    "HDL",     # HDL cholesterol
    "TRIGLY",  # triglycerides / LDL
    "DIQ",     # diabetes questionnaire
    "BPQ",     # blood pressure questionnaire
    "SMQ",     # smoking questionnaire
    "MCQ",     # medical conditions questionnaire
    "RXQ_RX",  # prescription medications
]
NHANES_URL = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{year}/DataFiles/{name}.{ext}"

GITHUB_ZIPS = {
    # name: (zip url, glob of members to keep inside the archive or None for all)
    "mimic_docs": (
        "https://codeload.github.com/MIT-LCP/mimic-website/zip/refs/heads/main",
        re.compile(r"^[^/]+/docs/iv/(about|modules/(hosp|icu|core))/.+\.md$"),
    ),
    "omop_etl": (
        "https://codeload.github.com/OHDSI/MIMIC/zip/refs/heads/main",
        None,
    ),
}
OMOP_SPEC_URLS = [
    "https://raw.githubusercontent.com/OHDSI/CommonDataModel/main/inst/csv/OMOP_CDMv5.3_Table_Level.csv",
    "https://raw.githubusercontent.com/OHDSI/CommonDataModel/main/inst/csv/OMOP_CDMv5.3_Field_Level.csv",
]

USER_AGENT = "ADSP32018-course-project-ingest/1.0 (academic use)"
TIMEOUT = 60

log = logging.getLogger("ingest")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

@dataclass
class FileRecord:
    source: str
    url: str
    path: str
    status: str          # downloaded | skipped_existing | missing | failed
    bytes: int = 0
    sha256: str = ""
    note: str = ""
    fetched_at: str = ""


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = USER_AGENT
    return s


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(session: requests.Session, url: str, dest: Path, source: str,
             force: bool = False) -> FileRecord:
    """Stream url -> dest atomically. Never raises; returns a FileRecord."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return FileRecord(source, url, str(dest), "skipped_existing",
                          dest.stat().st_size, sha256_of(dest), fetched_at=now)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with session.get(url, stream=True, timeout=TIMEOUT) as r:
            if r.status_code == 404:
                return FileRecord(source, url, str(dest), "missing", note="HTTP 404", fetched_at=now)
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        # CDC sometimes answers a missing file with an HTML error page + 200
        if dest.suffix.lower() == ".xpt" and "html" in ctype.lower():
            tmp.unlink(missing_ok=True)
            return FileRecord(source, url, str(dest), "missing",
                              note="server returned HTML instead of XPT", fetched_at=now)
        tmp.replace(dest)
        return FileRecord(source, url, str(dest), "downloaded",
                          dest.stat().st_size, sha256_of(dest), fetched_at=now)
    except Exception as e:  # noqa: BLE001 - we want to log and keep going
        tmp.unlink(missing_ok=True)
        return FileRecord(source, url, str(dest), "failed", note=repr(e)[:300], fetched_at=now)


# ---------------------------------------------------------------------------
# PhysioNet
# ---------------------------------------------------------------------------

class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def parse_listing(html: str, base_url: str) -> tuple[list[str], list[str]]:
    """Return (file_urls, subdir_urls) found in a directory-index page,
    restricted to children of base_url."""
    p = _LinkParser()
    p.feed(html)
    files, dirs = [], []
    for href in p.links:
        if href.startswith(("?", "#", "mailto:")) or href in ("../", "./"):
            continue
        full = urljoin(base_url, href)
        if not full.startswith(base_url) or full == base_url:
            continue
        (dirs if full.endswith("/") else files).append(full)
    return sorted(set(files)), sorted(set(dirs))


def crawl_physionet(session, base_url: str, max_depth: int = 6) -> list[str]:
    out, queue = [], [(base_url, 0)]
    while queue:
        url, depth = queue.pop()
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        files, dirs = parse_listing(r.text, url)
        out.extend(files)
        if depth < max_depth:
            queue.extend((d, depth + 1) for d in dirs)
    return sorted(out)


def list_s3_prefix(session, prefix: str) -> list[str]:
    keys, token = [], None
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        r = session.get(PHYSIONET_S3, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        keys += [k.text for k in root.findall("s3:Contents/s3:Key", ns)
                 if k.text and not k.text.endswith("/")]
        if root.findtext("s3:IsTruncated", default="false", namespaces=ns) != "true":
            break
        token = root.findtext("s3:NextContinuationToken", namespaces=ns)
    return keys


def verify_sha256sums(project_dir: Path) -> tuple[int, list[str]]:
    """PhysioNet ships SHA256SUMS.txt; check every listed file."""
    sums = project_dir / "SHA256SUMS.txt"
    if not sums.exists():
        return 0, []
    ok, bad = 0, []
    for line in sums.read_text().splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, rel = parts[0], parts[1].lstrip("*")
        f = project_dir / rel
        if not f.exists():
            bad.append(f"missing: {rel}")
        elif sha256_of(f) != digest:
            bad.append(f"checksum mismatch: {rel}")
        else:
            ok += 1
    return ok, bad


def fetch_physionet(session, raw: Path, force: bool) -> list[FileRecord]:
    records = []
    for slug, version, folder in PHYSIONET_PROJECTS:
        base = PHYSIONET_FILES.format(slug=slug, version=version)
        dest_root = raw / "physionet" / folder
        log.info("PhysioNet %s v%s", slug, version)
        try:
            urls = crawl_physionet(session, base)
            pairs = [(u, dest_root / u[len(base):]) for u in urls]
        except Exception as e:  # noqa: BLE001
            log.warning("  listing failed (%s); trying the open S3 mirror", e)
            try:
                prefix = f"{slug}/{version}/"
                keys = list_s3_prefix(session, prefix)
                pairs = [(PHYSIONET_S3 + k, dest_root / k[len(prefix):]) for k in keys]
            except Exception as e2:  # noqa: BLE001
                log.error("  S3 fallback failed too: %s", e2)
                records.append(FileRecord(f"physionet:{folder}", base, str(dest_root),
                                          "failed", note=f"could not list files: {e2!r}"[:300]))
                continue
        if not pairs:
            log.error("  no files found under %s", base)
            continue
        for url, dest in pairs:
            records.append(download(session, url, dest, f"physionet:{folder}", force))
        ok, bad = verify_sha256sums(dest_root)
        log.info("  %d files, %d checksums verified%s", len(pairs), ok,
                 f", {len(bad)} PROBLEMS" if bad else "")
        for b in bad[:10]:
            log.warning("    %s", b)
    return records


# ---------------------------------------------------------------------------
# NHANES
# ---------------------------------------------------------------------------

def fetch_nhanes(session, raw: Path, docs: Path, force: bool) -> list[FileRecord]:
    records = []
    for cycle, (year, suffix) in NHANES_CYCLES.items():
        log.info("NHANES %s", cycle)
        for comp in NHANES_COMPONENTS:
            name = f"{comp}_{suffix}"
            for ext, sub in (("xpt", "data"), ("htm", "docs")):
                url = NHANES_URL.format(year=year, name=name, ext=ext)
                dest = raw / "nhanes" / cycle / sub / f"{name}.{ext}"
                rec = download(session, url, dest, f"nhanes:{cycle}", force)
                records.append(rec)
                if rec.status == "missing":
                    log.info("  %s.%s not published for this cycle - skipped", name, ext)
                elif rec.status == "failed":
                    log.warning("  %s.%s failed: %s", name, ext, rec.note)
                elif ext == "htm":
                    (docs / "nhanes").mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, docs / "nhanes" / f"{cycle}_{name}.htm")
    return records


# ---------------------------------------------------------------------------
# GitHub sources (docs, ETL, OMOP spec)
# ---------------------------------------------------------------------------

def fetch_github(session, raw: Path, docs: Path, force: bool) -> list[FileRecord]:
    records = []
    for name, (url, keep) in GITHUB_ZIPS.items():
        log.info("GitHub %s", name)
        zpath = raw / "github" / f"{name}.zip"
        rec = download(session, url, zpath, f"github:{name}", force)
        records.append(rec)
        if rec.status not in ("downloaded", "skipped_existing"):
            log.warning("  failed: %s", rec.note)
            continue
        with zipfile.ZipFile(zpath) as zf:
            members = [m for m in zf.namelist()
                       if not m.endswith("/") and (keep is None or keep.match(m))]
            if name == "mimic_docs":
                out = docs / "mimic"
                out.mkdir(parents=True, exist_ok=True)
                for m in members:
                    # docs/iv/modules/hosp/labevents.md -> hosp__labevents.md
                    parts = Path(m).parts
                    tail = parts[parts.index("iv") + 1:]
                    flat = "__".join(p for p in tail if p != "modules")
                    (out / flat).write_bytes(zf.read(m))
                log.info("  %d MIMIC doc pages -> %s", len(members), out)
            else:
                out = raw / "github" / name
                if out.exists() and force:
                    shutil.rmtree(out)
                zf.extractall(out, members)
                log.info("  extracted %d files -> %s", len(members), out)

    for url in OMOP_SPEC_URLS:
        dest = docs / "omop" / Path(urlparse(url).path).name
        records.append(download(session, url, dest, "github:omop_spec", force))
    log.info("OMOP CDM v5.3 spec -> %s", docs / "omop")
    return records


# ---------------------------------------------------------------------------
# Post-download checks and DuckDB load
# ---------------------------------------------------------------------------

def _read_ids(path: Path, col: str):
    import pandas as pd
    df = pd.read_csv(path, usecols=lambda c: c.lower() == col, dtype=str)
    if df.empty or df.shape[1] == 0:
        return None
    return set(df.iloc[:, 0].dropna().str.strip())


def check_alignment(raw: Path) -> None:
    """Confirm the OMOP ground truth covers the same patients as each MIMIC demo."""
    pn = raw / "physionet"
    person = next((p for p in (pn / "omop_demo_v0_9").rglob("*") if p.name.lower() == "person.csv"), None)
    if person is None:
        log.warning("Alignment check skipped: OMOP person.csv not found")
        return
    omop_ids = _read_ids(person, "person_source_value")
    if not omop_ids:
        log.warning("Alignment check skipped: person_source_value column not found in %s", person)
        return
    for folder in ("mimic_demo_v1_0", "mimic_demo_v2_2"):
        pat = next((p for p in (pn / folder).rglob("patients.csv*")), None)
        if pat is None:
            continue
        mimic_ids = _read_ids(pat, "subject_id")
        both = len(mimic_ids & omop_ids)
        log.info("Alignment %s vs OMOP: %d MIMIC patients, %d OMOP persons, %d in both",
                 folder, len(mimic_ids), len(omop_ids), both)
        if both < len(omop_ids):
            log.warning("  %d OMOP persons not in %s - account for this when scoring",
                        len(omop_ids) - both, folder)


def _ident(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]", "_", s).strip("_").lower()


def build_duckdb(data_dir: Path, raw: Path) -> None:
    try:
        import duckdb
        import pandas as pd
    except ImportError:
        log.warning("duckdb/pandas not installed - skipping database build")
        return
    db_path = data_dir / "project.duckdb"
    con = duckdb.connect(str(db_path))
    loaded, failed = 0, []

    # MIMIC + OMOP: schema = dataset[_module], table = file stem
    for _, _, folder in PHYSIONET_PROJECTS:
        root = raw / "physionet" / folder
        for f in sorted(root.rglob("*.csv*")):
            if f.name.endswith(".part"):
                continue
            rel = f.relative_to(root).parts
            module = rel[0] if len(rel) > 1 else ""
            if folder.startswith("omop"):
                module = ""  # OMOP tables live in one schema regardless of folder
            schema = _ident(f"{folder}_{module}" if module else folder)
            table = _ident(f.name.split(".csv")[0])
            try:
                con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                con.execute(
                    f'CREATE OR REPLACE TABLE "{schema}"."{table}" AS '
                    f"SELECT * FROM read_csv(?, auto_detect=true, sample_size=-1, header=true)",
                    [str(f)],
                )
                loaded += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{schema}.{table}: {e}"[:200])

    # NHANES: schema = nhanes_<cycle>, table = component
    for cycle in NHANES_CYCLES:
        schema = _ident(f"nhanes_{cycle}")
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        for f in sorted((raw / "nhanes" / cycle / "data").glob("*.xpt")):
            try:
                df = pd.read_sas(f, format="xport", encoding="latin-1")
                con.register("_tmp", df)
                con.execute(f'CREATE OR REPLACE TABLE "{schema}"."{_ident(f.stem)}" AS SELECT * FROM _tmp')
                con.unregister("_tmp")
                loaded += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{schema}.{f.stem}: {e}"[:200])

    con.close()
    log.info("DuckDB: %d tables loaded -> %s", loaded, db_path)
    for msg in failed:
        log.warning("  load failed %s", msg)


def write_manifest(data_dir: Path, records: list[FileRecord]) -> None:
    path = data_dir / "manifest.json"
    old = {}
    if path.exists():
        old = {r["path"]: r for r in json.loads(path.read_text()).get("files", [])}
    for r in records:
        old[r.path] = asdict(r)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "files": sorted(old.values(), key=lambda r: r["path"])}
    path.write_text(json.dumps(payload, indent=2))

    counts: dict[str, int] = {}
    for r in records:
        counts[r.status] = counts.get(r.status, 0) + 1
    log.info("Manifest -> %s  %s", path, counts)
    failures = [r for r in records if r.status == "failed"]
    for r in failures[:15]:
        log.error("  FAILED %s  (%s)", r.url, r.note)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default="data", type=Path)
    ap.add_argument("--only", choices=["physionet", "nhanes", "docs", "all"], default="all")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    ap.add_argument("--no-duckdb", action="store_true", help="skip building project.duckdb")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    data_dir: Path = args.data_dir
    raw, docs = data_dir / "raw", data_dir / "docs"
    raw.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    session = make_session()

    records: list[FileRecord] = []
    if args.only in ("physionet", "all"):
        records += fetch_physionet(session, raw, args.force)
    if args.only in ("nhanes", "all"):
        records += fetch_nhanes(session, raw, docs, args.force)
    if args.only in ("docs", "all"):
        records += fetch_github(session, raw, docs, args.force)

    write_manifest(data_dir, records)
    if args.only in ("physionet", "all"):
        check_alignment(raw)
    if not args.no_duckdb:
        build_duckdb(data_dir, raw)

    return 1 if any(r.status == "failed" for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())