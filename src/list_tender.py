import argparse
import requests
import os
import time
import re
import json
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("SAM_KEY")
if not API_KEY:
    raise EnvironmentError("SAM_KEY environment variable is not set.")
KNOWLEDGE_BASE_DIR = os.path.join(os.getcwd(), "knowledge_base")
RESULTS_DIR        = os.path.join(os.getcwd(), "search_results")
DOWNLOAD_DELAY_SECONDS = 2
DEBUG_PRINT_JSON = False

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="List (and optionally download) SAM.gov tenders")
parser.add_argument(
    "--download",
    action="store_true",
    default=False,
    help="Actually download attachment files to knowledge_base/. "
         "Omit this flag to list only (no API download calls made).",
)
args = parser.parse_args()
DOWNLOAD_ENABLED = args.download

# ---------------------------------------------------------------------------
# SAM.gov search  – TWO requests total (one per notice type)
# Client-side NAICS filter keeps only genuine construction results.
# ---------------------------------------------------------------------------
BASE_URL = "https://api.sam.gov/opportunities/v2/search"

BASE_PARAMS = {
    "api_key":      API_KEY,
    "postedFrom":   "03/17/2026",
    "postedTo":     "04/17/2026",
    "keyword":      "construction",   # broad keyword, no state/NAICS restriction
    "limit":        1000,
    "active":       "Yes",
    "includeCount": "true",
    # No "state" — nationwide
    # No "ncode" — all NAICS
    # No "ptype" — all notice types (solicitation, combined synopsis, etc.)
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_folder_name(name: str) -> str:
    """Replace characters that are invalid in folder names."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def human_readable_size(num_bytes: int) -> str:
    """Return a human-friendly file-size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def collect_download_links(opportunity: dict) -> list[dict]:
    """
    Extract all downloadable resource links from an opportunity record.
    Returns a list of dicts: {"url": ..., "filename": ...}
    """
    links = []

    # SAM.gov v2 stores attachments under 'resourceLinks' or 'attachments'
    for field in ("resourceLinks", "attachments"):
        items = opportunity.get(field) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    href = item.get("url") or item.get("uri") or item.get("link") or ""
                    name = item.get("name") or item.get("fileName") or os.path.basename(href.split("?")[0]) or "file"
                    if href:
                        links.append({"url": href, "filename": name})
                elif isinstance(item, str) and item.startswith("http"):
                    links.append({"url": item, "filename": os.path.basename(item.split("?")[0]) or "file"})

    # Some records expose a single attachmentLink string
    single = opportunity.get("attachmentLink") or opportunity.get("attachmentUrl")
    if single and isinstance(single, str) and single.startswith("http"):
        fname = os.path.basename(single.split("?")[0]) or "attachment"
        links.append({"url": single, "filename": fname})

    return links


# Maps common MIME types to file extensions
MIME_TO_EXT = {
    "application/pdf":                                          ".pdf",
    "application/msword":                                       ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel":                                 ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint":                            ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/zip":                                          ".zip",
    "application/x-zip-compressed":                            ".zip",
    "text/plain":                                               ".txt",
    "text/html":                                                ".html",
    "image/jpeg":                                               ".jpg",
    "image/png":                                                ".png",
}


def resolve_filename(hint: str, resp: requests.Response) -> str:
    """
    Determine the best filename (with extension) for a downloaded file.
    Priority:
      1. Content-Disposition header (filename= or filename*=)
      2. Original hint if it already has an extension
      3. Extension inferred from Content-Type
      4. Fall back to hint as-is
    """
    # 1. Content-Disposition
    cd = resp.headers.get("Content-Disposition", "")
    if cd:
        # RFC 5987 extended value  filename*=UTF-8''foo%20bar.pdf
        m = re.search(r"filename\*=[^']*''([^\s;]+)", cd, re.IGNORECASE)
        if m:
            from urllib.parse import unquote
            return sanitize_folder_name(unquote(m.group(1)))
        # Plain  filename="foo.pdf"  or  filename=foo.pdf
        m = re.search(r'filename=["\']?([^"\';\r\n]+)["\']?', cd, re.IGNORECASE)
        if m:
            return sanitize_folder_name(m.group(1).strip())

    # 2. Hint already has an extension
    if os.path.splitext(hint)[1]:
        return hint

    # 3. Infer from Content-Type
    ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    ext = MIME_TO_EXT.get(ct, "")
    if ext:
        return hint + ext

    # 4. Give up – use hint as-is
    return hint


def download_file(url: str, dest_path: str, api_key: str) -> tuple:
    """
    Download a file.  Returns (bytes_written, resolved_filename).
    dest_path is treated as a *stem* – the final path may gain an extension.
    """
    headers = {"X-Api-Key": api_key}
    try:
        resp = requests.get(url, headers=headers, timeout=60, stream=True)
        if resp.status_code == 200:
            stem     = os.path.basename(dest_path)
            resolved = resolve_filename(stem, resp)
            final_path = os.path.join(os.path.dirname(dest_path), resolved)
            with open(final_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
            return os.path.getsize(final_path), resolved
        else:
            print(f"      ⚠  Could not download {url}  (HTTP {resp.status_code})")
            return 0, os.path.basename(dest_path)
    except Exception as exc:
        print(f"      ⚠  Error downloading {url}: {exc}")
        return 0, os.path.basename(dest_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if DOWNLOAD_ENABLED:
    os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
    print(f"📁  Knowledge base directory: {KNOWLEDGE_BASE_DIR}\n")
else:
    print("ℹ️   List-only mode. Use --download to save files to knowledge_base/.\n")

summary_rows = []

try:
    # Single API request — no ptype, state, or NAICS filter
    print(f"🔍  Querying SAM.gov (1 request, nationwide, keyword=construction) …")
    resp = requests.get(BASE_URL, params=BASE_PARAMS)
    if resp.status_code != 200:
        raise RuntimeError(f"Query failed (HTTP {resp.status_code}): {resp.text[:300]}")

    batch = resp.json().get("opportunitiesData", [])
    seen_ids: set[str] = set()
    opportunities: list[dict] = []
    for opp in batch:
        uid = opp.get("noticeId") or opp.get("solicitationNumber", "")
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            opportunities.append(opp)

    print(f"    → {len(batch)} returned, {len(opportunities)} unique")

    # Sort: NAICS code ascending, then doc count descending within each NAICS
    opportunities.sort(key=lambda o: (
        str(o.get("naicsCode") or "999999"),
        -len(collect_download_links(o)),
    ))

    if DEBUG_PRINT_JSON:
        print(json.dumps(opportunities, indent=2))

    print(f"\nFound {len(opportunities)} construction tender(s).\n{'=' * 60}\n")

    # ── Build Markdown output ─────────────────────────────────────────────
    timestamp   = datetime.now().strftime("%Y-%m-%d_%H%M")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    md_path     = os.path.join(RESULTS_DIR, f"tenders_{timestamp}.md")
    md_lines: list[str] = [
        f"# SAM.gov Construction Tenders — Nationwide",
        f"",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Date range:** {BASE_PARAMS['postedFrom']} → {BASE_PARAMS['postedTo']}  ",
        f"**Keyword:** `construction`  ",
        f"**Total results:** {len(opportunities)}  ",
        f"**Sorted by:** NAICS code ↑, then document count ↓  ",
        f"",
        f"---",
        f"",
    ]

    for opportunity in opportunities:
        title               = opportunity.get("title", "N/A")
        agency              = opportunity.get("fullParentPathName") or opportunity.get("agency") or opportunity.get("departmentName", "N/A")
        solicitation_number = opportunity.get("solicitationNumber") or opportunity.get("noticeId", "UNKNOWN")
        posted_date         = opportunity.get("postedDate", "N/A")
        response_deadline   = opportunity.get("responseDeadLine", "N/A")
        notice_type         = opportunity.get("type", "N/A")
        naics_code          = opportunity.get("naicsCode", "N/A")
        state               = (opportunity.get("placeOfPerformance") or {}).get("state", {}).get("code", "N/A")
        description         = (opportunity.get("description") or "")[:200]

        links = collect_download_links(opportunity)

        # Console output
        print(f"📋  {title}")
        print(f"    Agency       : {agency}")
        print(f"    Solicitation : {solicitation_number}")
        print(f"    NAICS        : {naics_code}  |  State: {state}")
        print(f"    Posted       : {posted_date}")
        print(f"    Deadline     : {response_deadline}")
        print(f"    Documents    : {len(links)} link(s) found")
        for idx, link_info in enumerate(links, start=1):
            print(f"      [{idx:>2}] {link_info['filename']}")
            print(f"            {link_info['url']}")

        # Markdown output
        md_lines += [
            f"## {title}",
            f"",
            f"| Field | Value |",
            f"|---|---|",
            f"| **Solicitation #** | `{solicitation_number}` |",
            f"| **Notice type** | {notice_type} |",
            f"| **NAICS** | {naics_code} |",
            f"| **State** | {state} |",
            f"| **Agency** | {agency} |",
            f"| **Posted** | {posted_date} |",
            f"| **Deadline** | {response_deadline} |",
        ]
        if description:
            md_lines += [f"| **Description** | {description}{'…' if len(description) == 200 else ''} |"]
        md_lines.append("")

        if links:
            md_lines.append(f"**Documents ({len(links)}):**")
            md_lines.append("")
            for idx, link_info in enumerate(links, start=1):
                md_lines.append(f"{idx}. [{link_info['filename']}]({link_info['url']})")
            md_lines.append("")
        else:
            md_lines.append("_No attachment links found._")
            md_lines.append("")

        md_lines.append("---")
        md_lines.append("")

        # Download flow
        folder_name      = sanitize_folder_name(solicitation_number)
        tender_dir       = os.path.join(KNOWLEDGE_BASE_DIR, folder_name)
        files_downloaded = 0
        total_bytes      = 0

        if DOWNLOAD_ENABLED and links:
            print()
            os.makedirs(tender_dir, exist_ok=True)
            for idx, link_info in enumerate(links, start=1):
                dest_filename = sanitize_folder_name(link_info["filename"]) or f"document_{idx}"
                dest_path     = os.path.join(tender_dir, dest_filename)
                print(f"      ↓ [{idx}/{len(links)}] downloading {link_info['filename']} …")
                bytes_written, saved_name = download_file(link_info["url"], dest_path, API_KEY)
                if bytes_written:
                    files_downloaded += 1
                    total_bytes      += bytes_written
                    print(f"         ✔  Saved {human_readable_size(bytes_written)} → {saved_name}")
                if idx < len(links):
                    time.sleep(DOWNLOAD_DELAY_SECONDS)
            print(f"    ✅  Downloaded {files_downloaded} file(s) ({human_readable_size(total_bytes)})\n")
        else:
            print(f"    ℹ️   Run with --download to fetch these files.\n")

        summary_rows.append({
            "title":             title,
            "agency":            agency,
            "solicitation":      solicitation_number,
            "naics":             naics_code,
            "posted":            posted_date,
            "deadline":          response_deadline,
            "notice_type":       notice_type,
            "description":       description,
            "links_found":       len(links),
            "files_downloaded":  files_downloaded,
            "total_bytes":       total_bytes,
        })

    # Write Markdown file
    Path(md_path).write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n📄  Results saved to: {md_path}")

except Exception as exc:
    import traceback
    print(f"An error occurred: {exc}")
    traceback.print_exc()

# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------
if summary_rows:
    grand_files = sum(r["files_downloaded"] for r in summary_rows)
    grand_bytes = sum(r["total_bytes"]       for r in summary_rows)

    print("\n" + "=" * 70)
    print(f"  SUMMARY  —  {len(summary_rows)} tender(s) returned")
    print("=" * 70)
    for i, row in enumerate(summary_rows, start=1):
        doc_label = f"{row['links_found']} doc(s)"
        print(f"  [{i:>2}] {row['title'][:60]}")
        print(f"        {row['solicitation']}  |  NAICS {row['naics']}  |  {doc_label}  |  deadline {row['deadline']}")
    if DOWNLOAD_ENABLED:
        print(f"\n  Downloaded: {grand_files} file(s)  |  {human_readable_size(grand_bytes)}")
    print("=" * 70)
else:
    print("\nNo construction tenders were retrieved.")
