"""Core velocity computation for autofac."""

import statistics

from gitutil import get_commits, diff_stat


def median_velocity(repo_dir, cap_hours=0, author=""):
    """Return the median velocity (lines/hour) for *repo_dir*, or None."""
    commits = get_commits(repo_dir, author=author)
    if len(commits) < 2:
        return None

    cap_sec = cap_hours * 3600 if cap_hours > 0 else 0
    velocities = []
    for i in range(len(commits) - 1):
        sha, ts = commits[i]
        prev_sha, prev_ts = commits[i + 1]

        added, removed = diff_stat(repo_dir, prev_sha, sha)
        delta = added + removed

        gap_sec = ts - prev_ts
        if gap_sec <= 0:
            interval = 0
        elif cap_sec > 0:
            interval = min(gap_sec, cap_sec)
        else:
            interval = gap_sec
        capped_hours = interval / 3600

        if interval > 0:
            velocities.append(delta / capped_hours)
        elif delta > 0:
            pass  # skip infinite velocity intervals

    if not velocities:
        return None
    return statistics.median(velocities)
