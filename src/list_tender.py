import requests
import os
import time
import re
import json

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("SAM_KEY")
if not API_KEY:
    raise EnvironmentError("SAM_KEY environment variable is not set.")
KNOWLEDGE_BASE_DIR = os.path.join(os.getcwd(), "knowledge_base")
DOWNLOAD_DELAY_SECONDS = 2   # polite pause between file downloads
DEBUG_PRINT_JSON = False      # set to True to dump the full API response JSON

# ---------------------------------------------------------------------------
# SAM.gov search endpoint
# ---------------------------------------------------------------------------
url = "https://api.sam.gov/opportunities/v2/search"

params = {
    "api_key": API_KEY,
    "postedFrom": "03/11/2026",
    "postedTo": "04/11/2026",
    "state": "CA",
    "ncode": "236220",   # NAICS 236220 – Commercial & Institutional Building Construction
    "limit": 5,
    "ptype": "s",                    # s = Solicitation (Open for bid)
    "active": "Yes",                 # Eliminates archived/closed projects
    "includeCount": "true",
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

# Ensure the knowledge_base folder exists
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
print(f"📁  Knowledge base directory: {KNOWLEDGE_BASE_DIR}\n")

summary_rows = []   # one entry per tender

try:
    response = requests.get(url, params=params)

    if response.status_code != 200:
        print(f"Failed to retrieve data. Status Code: {response.status_code}")
        print(response.text)
    else:
        data = response.json()

        if DEBUG_PRINT_JSON:
            print("DEBUG – full API response JSON:")
            print(json.dumps(data, indent=2))
            print("-" * 60 + "\n")

        opportunities = data.get("opportunitiesData", [])
        print(f"Found {len(opportunities)} tender(s).\n{'=' * 60}\n")

        for opportunity in opportunities:
            title              = opportunity.get("title", "N/A")
            agency             = opportunity.get("fullParentPathName") or opportunity.get("agency") or opportunity.get("departmentName", "N/A")
            solicitation_number = opportunity.get("solicitationNumber") or opportunity.get("noticeId", "UNKNOWN")
            posted_date        = opportunity.get("postedDate", "N/A")
            response_deadline  = opportunity.get("responseDeadLine", "N/A")
            notice_type        = opportunity.get("type", "N/A")
            description        = (opportunity.get("description") or "")[:200]  # first 200 chars

            print(f"📋  {title}")
            print(f"    Agency       : {agency}")
            print(f"    Solicitation : {solicitation_number}")
            print(f"    Posted       : {posted_date}")
            print(f"    Deadline     : {response_deadline}")

            # --- create subfolder ---
            folder_name = sanitize_folder_name(solicitation_number)
            tender_dir  = os.path.join(KNOWLEDGE_BASE_DIR, folder_name)
            os.makedirs(tender_dir, exist_ok=True)

            # --- gather links and download ---
            links = collect_download_links(opportunity)
            print(f"    Documents    : {len(links)} link(s) found")

            files_downloaded = 0
            total_bytes      = 0

            for idx, link_info in enumerate(links, start=1):
                dest_filename = sanitize_folder_name(link_info["filename"]) or f"document_{idx}"
                dest_path     = os.path.join(tender_dir, dest_filename)

                print(f"      ↓ [{idx}/{len(links)}] {link_info['url']}")
                bytes_written, saved_name = download_file(link_info["url"], dest_path, API_KEY)

                if bytes_written:
                    files_downloaded += 1
                    total_bytes      += bytes_written
                    print(f"         ✔  Saved {human_readable_size(bytes_written)} → {saved_name}")

                # polite delay between downloads
                if idx < len(links):
                    time.sleep(DOWNLOAD_DELAY_SECONDS)

            print(f"    ✅  Downloaded {files_downloaded} file(s) "
                  f"({human_readable_size(total_bytes)})\n")

            summary_rows.append({
                "title":             title,
                "agency":            agency,
                "solicitation":      solicitation_number,
                "posted":            posted_date,
                "deadline":          response_deadline,
                "notice_type":       notice_type,
                "description":       description,
                "links_found":       len(links),
                "files_downloaded":  files_downloaded,
                "total_bytes":       total_bytes,
            })

except Exception as exc:
    print(f"An error occurred: {exc}")

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
if summary_rows:
    grand_files = sum(r["files_downloaded"] for r in summary_rows)
    grand_bytes = sum(r["total_bytes"]       for r in summary_rows)

    print("\n" + "=" * 70)
    print("  DOWNLOAD SUMMARY")
    print("=" * 70)

    for i, row in enumerate(summary_rows, start=1):
        print(f"\n  [{i}] {row['title']}")
        print(f"       Type          : {row['notice_type']}")
        print(f"       Agency        : {row['agency']}")
        print(f"       Solicitation  : {row['solicitation']}")
        print(f"       Posted        : {row['posted']}")
        print(f"       Deadline      : {row['deadline']}")
        if row["description"]:
            print(f"       Description   : {row['description']}{'…' if len(row['description']) == 200 else ''}")
        print(f"       Links found   : {row['links_found']}")
        print(f"       Files saved   : {row['files_downloaded']}")
        print(f"       Storage used  : {human_readable_size(row['total_bytes'])}")
        print(f"       Folder        : knowledge_base/{sanitize_folder_name(row['solicitation'])}")

    print("\n" + "-" * 70)
    print(f"  TOTAL  →  {grand_files} file(s) downloaded  |  "
          f"{human_readable_size(grand_bytes)} total storage used")
    print("=" * 70)
else:
    print("\nNo tenders were retrieved – nothing to summarise.")
