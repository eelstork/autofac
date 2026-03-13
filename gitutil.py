"""Git and GitHub helpers for autofac."""

import json
import subprocess
import urllib.request


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


def clone_repo(clone_url, dest):
    subprocess.run(
        ["git", "clone", "--quiet", clone_url, dest],
        capture_output=True, text=True,
    )
