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
    """Return list of repos for *username* via the GitHub API.

    When *token* is provided, uses the authenticated endpoint which
    includes private repositories.  Without a token, only public repos
    are returned.

    Each item has at least 'name', 'clone_url', 'size' (KB), 'fork'.
    """
    if token:
        # Authenticated: gets all repos (public + private) for the token owner
        url = f"https://api.github.com/user/repos?per_page=100&affiliation=owner"
        all_repos = github_get(url, token=token)
        # Filter to the requested username (the token may belong to them,
        # but this keeps behaviour predictable)
        return [r for r in all_repos if r["owner"]["login"].lower() == username.lower()]
    else:
        url = f"https://api.github.com/users/{username}/repos?per_page=100&type=owner"
        return github_get(url, token=None)


def git_in(repo_dir, *args):
    r = subprocess.run(
        ["git", "-C", repo_dir] + list(args),
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def get_commits(repo_dir, author="", exclude_author=""):
    cmd = ["log", "--format=%H %at %aN", "--no-merges"]
    if author:
        cmd += [f"--author={author}"]
    excludes = [e.strip().lower() for e in exclude_author.split(",") if e.strip()] if exclude_author else []
    lines = git_in(repo_dir, *cmd).splitlines()
    commits = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 2:
            name = parts[2] if len(parts) == 3 else ""
            if excludes and any(ex in name.lower() for ex in excludes):
                continue
            commits.append((parts[0], int(parts[1]), name))
    return commits


def list_authors(repo_dir):
    """Return sorted list of unique author names in the repo."""
    lines = git_in(repo_dir, "log", "--format=%aN", "--no-merges").splitlines()
    return sorted(set(line.strip() for line in lines if line.strip()))


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
