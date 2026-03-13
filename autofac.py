#!/usr/bin/env python3
"""autofac — Cross-project velocity aggregator.

Downloads all public repositories for a GitHub user (with optional
max-size filter), computes the median commit velocity for each project,
and outputs the averaged median velocity across all projects.

Repo sizes are checked via the GitHub API *before* cloning so that
oversized repositories can be skipped without downloading them.

Usage:
  python3 autofac.py <github-username>
  python3 autofac.py <github-username> --max-size=50      # skip repos > 50 MB
  python3 autofac.py <github-username> --cap=72           # cap commit interval at 72h (off by default)
  python3 autofac.py <github-username> --workdir=/tmp/af  # clone into custom dir
  python3 autofac.py <github-username> --token=ghp_...    # use a GitHub token
"""

import argparse
import os
import shutil
import statistics
import sys
import urllib.error

from gitutil import list_repos, clone_repo
from core import median_velocity


def main():
    parser = argparse.ArgumentParser(
        description="Cross-project velocity aggregator",
    )
    parser.add_argument("username", help="GitHub username")
    parser.add_argument(
        "--max-size", type=int, default=0,
        help="Skip repos larger than this (MB). 0 = no limit.",
    )
    parser.add_argument(
        "--cap", type=float, default=0,
        help="Cap commit-interval hours. 0 = no cap (default).",
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

        # Always skip forks
        if is_fork:
            skipped_fork += 1
            continue

        # Size gate (checked *before* cloning)
        max_size_kb = args.max_size * 1024
        if args.max_size and size_kb > max_size_kb:
            print(f"  SKIP  {name:30s}  {size_kb // 1024:>6,} MB  (exceeds --max-size)")
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
