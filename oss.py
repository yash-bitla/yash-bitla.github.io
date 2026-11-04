"""Open-source contributions for the /oss/ page.

At build time, fetch every GitHub thread that involves the user outside their own repos,
keep merged PRs and work in progress, and cache the result in content/oss.json.
If GitHub cannot be reached (offline, no token), the last cache is used.
"""

import json
import os
import subprocess
import urllib.request
from datetime import date, datetime
from pathlib import Path

USER = "yash-bitla"

QUERY = """
query($q: String!) { search(query: $q, type: ISSUE, first: 50) { nodes {
  ... on PullRequest { __typename number title url state createdAt mergedAt merged additions deletions
    author { login } repository { nameWithOwner stargazerCount primaryLanguage { name } }
    closingIssuesReferences(first: 3) { nodes { number title url createdAt } } }
  ... on Issue { __typename number title url state createdAt
    author { login } repository { nameWithOwner stargazerCount primaryLanguage { name } }
    timelineItems(last: 40, itemTypes: [CROSS_REFERENCED_EVENT]) { nodes { ... on CrossReferencedEvent {
      source { ... on PullRequest { url author { login } } } } } } }
} } }
"""


def token() -> str | None:
    """GH_TOKEN or GITHUB_TOKEN in CI, the gh CLI login on a laptop."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def search(query: str, auth: str) -> list[dict]:
    body = json.dumps({"query": QUERY, "variables": {"q": query}}).encode()
    request = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {auth}", "Content-Type": "application/json", "User-Agent": "yashbitla.com-build"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if "errors" in data:
        raise RuntimeError(data["errors"][0].get("message", "GraphQL error"))
    return [n for n in data["data"]["search"]["nodes"] if n]


def day(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def repo_info(node: dict) -> dict:
    repo = node["repository"]
    return {"repo": repo["nameWithOwner"], "stars": repo["stargazerCount"],
            "language": (repo.get("primaryLanguage") or {}).get("name")}


def summarize(nodes: list[dict], hide: set[str], notes: dict[str, str]) -> dict:
    """Split nodes into merged PRs and work in progress. Pure: no network."""
    prs = [n for n in nodes if n["__typename"] == "PullRequest" and n["author"]["login"] == USER]
    issues = [n for n in nodes if n["__typename"] == "Issue"]
    linked: dict[str, list[dict]] = {}
    for pr in prs:
        refs = {i["url"]: i for i in pr["closingIssuesReferences"]["nodes"]}
        for issue in issues:
            sources = [(t.get("source") or {}) for t in issue["timelineItems"]["nodes"]]
            if any(s.get("url") == pr["url"] for s in sources):
                refs.setdefault(issue["url"], issue)
        linked[pr["url"]] = sorted(refs.values(), key=lambda i: i["number"])
    attached = {i["url"] for refs in linked.values() for i in refs}

    merged, active = [], []
    for pr in prs:
        if pr["url"] in hide or (pr["state"] != "OPEN" and not pr["merged"]):
            continue
        issue = linked[pr["url"]][0] if linked[pr["url"]] else None
        item = {**repo_info(pr), "kind": "PR", "number": pr["number"], "title": pr["title"], "url": pr["url"],
                "opened": day(pr["createdAt"]), "merged": day(pr["mergedAt"]),
                "additions": pr["additions"], "deletions": pr["deletions"], "note": notes.get(pr["url"], ""),
                "issue": {"number": issue["number"], "title": issue["title"], "url": issue["url"],
                          "opened": day(issue.get("createdAt"))} if issue else None}
        (merged if pr["merged"] else active).append(item)
    for issue in issues:
        if issue["url"] in attached or issue["url"] in hide or issue["state"] != "OPEN":
            continue
        active.append({**repo_info(issue), "kind": "Issue", "number": issue["number"], "title": issue["title"],
                       "url": issue["url"], "opened": day(issue["createdAt"]), "note": notes.get(issue["url"], "")})
    merged.sort(key=lambda m: m["merged"], reverse=True)
    active.sort(key=lambda a: (a["kind"] != "PR", a["repo"], a["number"]))
    return {"merged": merged, "active": active}


def fetch(hide: set[str], notes: dict[str, str]) -> dict:
    auth = token()
    if not auth:
        raise RuntimeError("no GitHub token")
    nodes: dict[str, dict] = {}
    for q in (f"author:{USER} -user:{USER} is:pr", f"involves:{USER} -user:{USER} is:issue is:open"):
        for node in search(q, auth):
            nodes[node["url"]] = node
    return summarize(list(nodes.values()), hide, notes)


def add_dates(data: dict) -> dict:
    """Turn ISO day strings into date objects and work out days to merge, for the template."""
    for item in data["merged"]:
        opened, merged = date.fromisoformat(item["opened"]), date.fromisoformat(item["merged"])
        item["days_to_merge"] = (merged - opened).days
        total = (item["additions"] or 0) + (item["deletions"] or 0)
        # GitHub's five-block diffstat: green share of the blocks, at least one block for any change.
        green = round(5 * item["additions"] / total) if total else 0
        item["blocks"] = ["add"] * green + ["del"] * (5 - green) if total else ["none"] * 5
    return data


def load(root: Path, config: dict) -> dict:
    """Fresh data when GitHub answers, else the cached copy. Writes the cache only when it changed."""
    cache = root / "content" / "oss.json"
    hide = set(config.get("hide", []))
    notes = {n["url"]: n["summary"] for n in config.get("notes", [])}
    try:
        data = fetch(hide, notes)
        text = json.dumps(data, indent=1, sort_keys=True) + "\n"
        if not cache.exists() or cache.read_text(encoding="utf-8") != text:
            cache.write_text(text, encoding="utf-8")
        source = "live"
    except Exception as error:  # the site must build without GitHub
        print(f"oss: using cache ({error})")
        data = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {"merged": [], "active": []}
        source = "cache"
    data = add_dates(data)
    data["updated"] = datetime.now().strftime("%b %-d, %Y")
    data["source"] = source
    return data
