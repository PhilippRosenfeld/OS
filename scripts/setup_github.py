"""Creates the labels, milestones and issues from github_data.yml on GitHub.

Existing items are skipped (labels and milestones by name/title, issues by
title), so the script can safely be run again after editing the data file.
It never edits or deletes anything that already exists.

    uv run python scripts/setup_github.py --dry-run
    GITHUB_TOKEN=... uv run python scripts/setup_github.py

The token needs write access to issues on the repository (a fine-grained
token with "Issues: Read and write", or a classic token with `repo` or
`public_repo`). It is read from --token or the GITHUB_TOKEN environment
variable and is never printed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

API = "https://api.github.com"
DATA_PATH = Path(__file__).with_name("github_data.yml")
PAUSE_SECONDS = 1.0  # GitHub asks for about a second between requests that create content


class GitHub:
    def __init__(self, repo: str, token: str | None) -> None:
        self.repo = repo
        self.token = token

    def request(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(f"{API}/repos/{self.repo}{path}", data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request) as response:
            body = response.read()
        return json.loads(body) if body else None

    def list(self, path: str) -> list[dict]:
        items, page = [], 1
        separator = "&" if "?" in path else "?"
        while True:
            batch = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


def repo_from_git() -> str | None:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def validate(data: dict) -> list[str]:
    """Problems in the data file that would otherwise only show up halfway through creating things."""
    problems = []
    known_labels = {label["name"] for label in data["labels"]}
    titles = set()
    for milestone in data["milestones"]:
        for issue in milestone["issues"]:
            title = issue["title"]
            if title in titles:
                problems.append(f"duplicate issue title: {title}")
            titles.add(title)
            for label in issue.get("labels", []):
                if label not in known_labels:
                    problems.append(f"'{title}' uses unknown label '{label}'")  # GitHub would silently create it
    return problems


def fetch_existing(gh: GitHub, path: str, dry_run: bool) -> list[dict]:
    try:
        return gh.list(path)
    except urllib.error.HTTPError as error:
        if not dry_run:
            raise
        print(f"  (could not read {path}: HTTP {error.code} -- assuming nothing exists yet)")
        return []


def sync_labels(gh: GitHub, labels: list[dict], dry_run: bool) -> None:
    print("Labels")
    existing = {label["name"].lower() for label in fetch_existing(gh, "/labels", dry_run)}
    for label in labels:
        if label["name"].lower() in existing:
            print(f"  skip    {label['name']}")
            continue
        print(f"  create  {label['name']}")
        if not dry_run:
            gh.request("POST", "/labels", {"name": label["name"], "color": label["color"], "description": label.get("description", "")})
            time.sleep(PAUSE_SECONDS)


def sync_milestones(gh: GitHub, milestones: list[dict], dry_run: bool) -> dict[str, int | None]:
    print("Milestones")
    numbers = {m["title"]: m["number"] for m in fetch_existing(gh, "/milestones?state=all", dry_run)}
    for milestone in milestones:
        title = milestone["title"]
        if title in numbers:
            print(f"  skip    {title}")
            continue
        print(f"  create  {title}")
        if dry_run:
            numbers[title] = None
            continue
        created = gh.request("POST", "/milestones", {"title": title, "description": milestone.get("description", "")})
        numbers[title] = created["number"]
        time.sleep(PAUSE_SECONDS)
    return numbers


def sync_issues(gh: GitHub, milestones: list[dict], numbers: dict[str, int | None], dry_run: bool) -> None:
    print("Issues")
    existing = {
        issue["title"]
        for issue in fetch_existing(gh, "/issues?state=all", dry_run)
        if "pull_request" not in issue  # the issues endpoint returns pull requests too
    }
    for milestone in milestones:
        for issue in milestone["issues"]:
            title = issue["title"]
            if title in existing:
                print(f"  skip    [{milestone['title']}] {title}")
                continue
            print(f"  create  [{milestone['title']}] {title}")
            if not dry_run:
                gh.request("POST", "/issues", {
                    "title": title,
                    "body": issue.get("body", "").strip(),
                    "labels": issue.get("labels", []),
                    "milestone": numbers[milestone["title"]],
                })
                time.sleep(PAUSE_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the labels, milestones and issues from github_data.yml.")
    parser.add_argument("--repo", help="owner/name (default: taken from the 'origin' remote)")
    parser.add_argument("--token", help="GitHub token (default: $GITHUB_TOKEN)")
    parser.add_argument("--data", type=Path, default=DATA_PATH, help="data file (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="only print what would be created")
    args = parser.parse_args()

    repo = args.repo or repo_from_git()
    if repo is None:
        print("Could not work out the repository, pass --repo owner/name.", file=sys.stderr)
        return 2
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token and not args.dry_run:
        print("No token: set GITHUB_TOKEN or pass --token (or use --dry-run).", file=sys.stderr)
        return 2

    data = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    problems = validate(data)
    if problems:
        print("Problems in the data file:", *problems, sep="\n  ", file=sys.stderr)
        return 1

    print(f"{'Dry run for' if args.dry_run else 'Setting up'} {repo}")
    gh = GitHub(repo, token)
    try:
        sync_labels(gh, data["labels"], args.dry_run)
        numbers = sync_milestones(gh, data["milestones"], args.dry_run)
        sync_issues(gh, data["milestones"], numbers, args.dry_run)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        print(f"GitHub answered HTTP {error.code}: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
