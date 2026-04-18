"""
One-off helper: scan a tenders markdown file and print candidates matching:
  - State in CA or neighboring states (AZ, NV, OR, WA, ID, UT)
  - Document count between 10 and 30
  - Title contains at least one construction-relevant keyword
"""
import re
import sys

MD_FILE = "search_results/tenders_2026-04-16_2155.md"
TARGET_STATES = {"CA", "AZ", "NV", "OR", "WA", "ID", "UT"}
MIN_DOCS, MAX_DOCS = 10, 30

# Keywords that suggest real construction work (vs. equipment/supplies)
CONSTRUCTION_KEYWORDS = re.compile(
    r"construct|repair|renovate|renovation|install|replace|upgrade|build|facility"
    r"|hangar|building|infrastructure|roof|pavement|paving|dam|bridge|road|trail"
    r"|plumbing|electrical|mechanical|hvac|chiller|boiler|clinic|hospital|school"
    r"|warehouse|barracks|dormitory|runway|taxiway|pier|wharf|bulkhead|levee"
    r"|water.tank|water.line|sewer|pipeline|utility|site.work",
    re.IGNORECASE,
)

with open(MD_FILE, encoding="utf-8") as f:
    content = f.read()

blocks = re.split(r"\n---\n", content)
results = []

for block in blocks:
    title_m    = re.search(r"^## (.+)$", block, re.MULTILINE)
    sol_m      = re.search(r"\*\*Solicitation #\*\* \| `(.+?)`", block)
    state_m    = re.search(r"\*\*State\*\* \| (\S+)", block)
    naics_m    = re.search(r"\*\*NAICS\*\* \| (\S+)", block)
    docs_m     = re.search(r"\*\*Documents \((\d+)\)", block)
    deadline_m = re.search(r"\*\*Deadline\*\* \| (\S+)", block)
    type_m     = re.search(r"\*\*Notice type\*\* \| (.+?) \|", block)

    if not (title_m and sol_m and state_m and docs_m):
        continue

    state    = state_m.group(1).strip()
    n_docs   = int(docs_m.group(1))
    naics    = naics_m.group(1).strip() if naics_m else ""
    title    = title_m.group(1).strip()
    sol      = sol_m.group(1).strip()
    deadline = deadline_m.group(1).strip() if deadline_m else "N/A"
    ntype    = type_m.group(1).strip() if type_m else ""

    if state not in TARGET_STATES:
        continue
    if not (MIN_DOCS <= n_docs <= MAX_DOCS):
        continue
    # Flag whether title looks like real construction work
    is_construction = bool(CONSTRUCTION_KEYWORDS.search(title))

    results.append((naics, -n_docs, state, title, sol, n_docs, deadline, ntype, is_construction))

results.sort()

print(f"{'#':<3} {'✓':<3} {'St':<3} {'NAICS':<8} {'Docs':<5} {'Solicitation':<28} {'Deadline':<22} Title")
print("-" * 140)
for i, (naics, neg, state, title, sol, n_docs, deadline, ntype, is_c) in enumerate(results, 1):
    flag = "✅" if is_c else "  "
    dl = deadline[:19] if deadline else "N/A"
    print(f"{i:<3} {flag} {state:<3} {naics:<8} {n_docs:<5} {sol:<28} {dl:<22} {title[:65]}")





