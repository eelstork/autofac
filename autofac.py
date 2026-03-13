#!/usr/bin/env python3
"""autofac — Cross-project velocity aggregator.

Downloads all public repositories for a GitHub user (with optional
max-size filter), computes the median commit velocity for each project,
and outputs the averaged median velocity across all projects.

Repo sizes are checked via the GitHub API *before* cloning so that
oversized repositories can be skipped without downloading them.

Usage:
  python3 autofac.py <github-username>
  python3 autofac.py <github-username> --max-size=50000   # skip repos > 50 MB
  python3 autofac.py <github-username> --cap=72           # cap commit interval at 72h
  python3 autofac.py <github-username> --workdir=/tmp/af  # clone into custom dir
  python3 autofac.py <github-username> --token=ghp_...    # use a GitHub token
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def github_get(url, token=None):
    """GET a GitHub API endpoint, following pagination."""
    results = []
    while url:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req) as resp:
            results.extend(json.loads(resp.read()))
            # Follow Link: <...>; rel="next"
            link = resp.headers.get("Link", "")
            url = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
    return results


def list_repos(username, token=None):
    """Return list of public repos for *username* via the GitHub API.

    Each item has at least 'name', 'clone_url', 'size' (KB), 'fork'.
    """
    url = f"https://api.github.com/users/{username}/repos?per_page=100&type=owner"
    return github_get(url, token=token)


# ---------------------------------------------------------------------------
# Velocity (adapted from commit-velocity.py in active-logic-cs)
# ---------------------------------------------------------------------------

def git_in(repo_dir, *args):
    r = subprocess.run(
        ["git", "-C", repo_dir] + list(args),
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def get_commits(repo_dir, author=""):
    cmd = ["log", "--format=%H %at", "--no-merges"]
    if author:
        cmd += [f"--author={author}"]
    lines = git_in(repo_dir, *cmd).splitlines()
    commits = []
    for line in lines:
        parts = line.split()
        if len(parts) == 2:
            commits.append((parts[0], int(parts[1])))
    return commits


def diff_stat(repo_dir, parent, child):
    lines = git_in(repo_dir, "diff", "--numstat", parent, child).splitlines()
    added = removed = 0
    for line in lines:
        parts = line.split()
        if not parts or parts[0] == "-":
            continue
        added += int(parts[0])
        removed += int(parts[1])
    return added, removed


def median_velocity(repo_dir, cap_hours=168, author=""):
    """Return the median velocity (lines/hour) for *repo_dir*, or None."""
    commits = get_commits(repo_dir, author=author)
    if len(commits) < 2:
        return None

    cap_sec = cap_hours * 3600
    velocities = []
    for i in range(len(commits) - 1):
        sha, ts = commits[i]
        prev_sha, prev_ts = commits[i + 1]

        added, removed = diff_stat(repo_dir, prev_sha, sha)
        delta = added + removed

        gap_sec = ts - prev_ts
        capped = min(gap_sec, cap_sec) if gap_sec > 0 else 0
        capped_hours = capped / 3600

        if capped > 0:
            velocities.append(delta / capped_hours)
        elif delta > 0:
            pass  # skip infinite velocity intervals

    if not velocities:
        return None
    return statistics.median(velocities)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def clone_repo(clone_url, dest):
    subprocess.run(
        ["git", "clone", "--quiet", clone_url, dest],
        capture_output=True, text=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Cross-project velocity aggregator",
    )
    parser.add_argument("username", help="GitHub username")
    parser.add_argument(
        "--max-size", type=int, default=0,
        help="Skip repos larger than this (KB). 0 = no limit.",
    )
    parser.add_argument(
        "--cap", type=float, default=168,
        help="Cap commit-interval hours (default 168 = 1 week)",
    )
    parser.add_argument(
        "--author", default="",
        help="Filter commits by author name",
    )
    parser.add_argument(
        "--workdir", default="",
        help="Directory to clone repos into (default: ./autofac_work)",
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub personal access token (or set GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--include-forks", action="store_true",
        help="Include forked repositories (excluded by default)",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep cloned repos after analysis (deleted by default)",
    )
    args = parser.parse_args()

    workdir = args.workdir or os.path.join(os.getcwd(), "autofac_work")
    os.makedirs(workdir, exist_ok=True)

    # ── 1. Fetch repo list ──────────────────────────────────────────────
    print(f"Fetching repositories for {args.username} …")
    try:
        repos = list_repos(args.username, token=args.token or None)
    except urllib.error.HTTPError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not repos:
        print("No repositories found.")
        sys.exit(0)

    print(f"Found {len(repos)} repo(s).\n")

    # ── 2. Filter & process ─────────────────────────────────────────────
    medians = []
    skipped_size = 0
    skipped_fork = 0
    skipped_empty = 0

    for repo in sorted(repos, key=lambda r: r["name"]):
        name = repo["name"]
        size_kb = repo.get("size", 0)
        is_fork = repo.get("fork", False)

        # Skip forks unless asked
        if is_fork and not args.include_forks:
            skipped_fork += 1
            continue

        # Size gate (checked *before* cloning)
        if args.max_size and size_kb > args.max_size:
            print(f"  SKIP  {name:30s}  {size_kb:>8,} KB  (exceeds --max-size)")
            skipped_size += 1
            continue

        dest = os.path.join(workdir, name)
        already_cloned = os.path.isdir(dest)

        if not already_cloned:
            print(f"  CLONE {name:30s}  {size_kb:>8,} KB  …", end="", flush=True)
            clone_repo(repo["clone_url"], dest)
            print("  ok")
        else:
            print(f"  EXIST {name:30s}  {size_kb:>8,} KB")

        med = median_velocity(dest, cap_hours=args.cap, author=args.author)

        if med is not None:
            medians.append((name, med))
            print(f"         → median velocity: {med:.1f} lines/hour")
        else:
            skipped_empty += 1
            print(f"         → too few commits, skipped")

        # Clean up unless --keep
        if not args.keep and not already_cloned:
            shutil.rmtree(dest, ignore_errors=True)

    # ── 3. Aggregate ────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if medians:
        values = [v for _, v in medians]
        avg_median = statistics.mean(values)

        print(f"{'Project':<30s}  {'Median vel (l/h)':>16s}")
        print("-" * 48)
        for name, v in medians:
            print(f"{name:<30s}  {v:>16.1f}")
        print("-" * 48)
        print(f"{'Averaged median velocity':<30s}  {avg_median:>16.1f} lines/hour")
        print(f"\nProjects analyzed: {len(medians)}")
    else:
        print("No projects with sufficient commit history.")

    if skipped_size:
        print(f"Skipped (size):  {skipped_size}")
    if skipped_fork:
        print(f"Skipped (fork):  {skipped_fork}")
    if skipped_empty:
        print(f"Skipped (empty): {skipped_empty}")

    # Cleanup workdir if empty
    if not args.keep:
        try:
            os.rmdir(workdir)
        except OSError:
            pass


if __name__ == "__main__":
    main()
