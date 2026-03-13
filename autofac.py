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
import subprocess
import sys
import urllib.error

from gitutil import list_repos, clone_repo, list_authors
from core import median_velocity


def main():
    parser = argparse.ArgumentParser(
        description="Cross-project velocity aggregator",
    )
    parser.add_argument("username", nargs="?", default="", help="GitHub username")
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
        "--exclude-author", default="",
        help="Exclude commits by author name (substring match)",
    )
    parser.add_argument(
        "--workdir", default="",
        help="Directory to clone repos into (default: ./autofac_work)",
    )
    parser.add_argument(
        "--token", default="",
        help="GitHub token (default: GITHUB_TOKEN env var, or gh auth token)",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep cloned repos after analysis (deleted by default)",
    )
    parser.add_argument(
        "--dry", action="store_true",
        help="Estimate max disk usage without cloning anything",
    )
    parser.add_argument(
        "--defaults", action="store_true",
        help="Display default parameter values and exit",
    )
    args = parser.parse_args()

    # Resolve token: explicit flag > env var > gh CLI
    if not args.token:
        args.token = os.environ.get("GITHUB_TOKEN", "")
    if not args.token:
        try:
            r = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                args.token = r.stdout.strip()
        except FileNotFoundError:
            pass  # gh not installed

    # ── 0. Show defaults ────────────────────────────────────────────────
    if args.defaults:
        print("Default parameters:")
        print(f"  max-size        {args.max_size or 'no limit'}")
        print(f"  cap             {args.cap or 'no cap'}")
        print(f"  author          {args.author or '(all)'}")
        print(f"  exclude-author  {args.exclude_author or '(none)'}")
        print(f"  workdir         {args.workdir or './autofac_work'}")
        print(f"  token           {'set' if args.token else 'not set'}")
        print(f"  keep            {args.keep}")
        print(f"  dry             {args.dry}")
        sys.exit(0)

    if not args.username:
        parser.error("username is required (unless using --defaults)")

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

    # ── 2. Filter repos ────────────────────────────────────────────────
    filtered = []
    skipped_size = 0
    skipped_fork = 0

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

        filtered.append(repo)

    # ── 2b. Dry run — estimate max disk usage ──────────────────────────
    if args.dry:
        sizes_kb = [r.get("size", 0) for r in filtered]
        if not sizes_kb:
            print("No repos to process.")
            sys.exit(0)

        if args.keep:
            max_kb = sum(sizes_kb)
            label = "total (--keep)"
        else:
            max_kb = max(sizes_kb)
            label = "largest single repo"

        max_mb = max_kb / 1024
        print(f"Repos to process: {len(filtered)}")
        print(f"Max disk usage ({label}): {max_mb:,.1f} MB")
        sys.exit(0)

    # ── 3. Clone & process ─────────────────────────────────────────────
    medians = []
    all_authors = set()
    skipped_empty = 0

    for repo in filtered:
        name = repo["name"]
        size_kb = repo.get("size", 0)
        dest = os.path.join(workdir, name)
        already_cloned = os.path.isdir(dest)

        if not already_cloned:
            print(f"  CLONE {name:30s}  {size_kb:>8,} KB  …", end="", flush=True)
            clone_repo(repo["clone_url"], dest)
            print("  ok")
        else:
            print(f"  EXIST {name:30s}  {size_kb:>8,} KB")

        # Collect authors seen in this repo
        authors = list_authors(dest)
        all_authors.update(authors)
        if authors:
            print(f"         authors: {', '.join(authors)}")

        med = median_velocity(
            dest, cap_hours=args.cap,
            author=args.author, exclude_author=args.exclude_author,
        )

        if med is not None and med > 0:
            medians.append((name, med))
            print(f"         → median velocity: {med:.1f} lines/hour")
        else:
            skipped_empty += 1
            print(f"         → too few commits, skipped")

        # Clean up unless --keep
        if not args.keep and not already_cloned:
            shutil.rmtree(dest, ignore_errors=True)

    # ── 4. Aggregate ────────────────────────────────────────────────────
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

    if all_authors:
        print(f"\nAuthors ({len(all_authors)}):")
        for a in sorted(all_authors):
            print(f"  {a}")

    # Cleanup workdir if empty
    if not args.keep:
        try:
            os.rmdir(workdir)
        except OSError:
            pass


if __name__ == "__main__":
    main()
