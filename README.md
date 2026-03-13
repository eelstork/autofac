# autofac

Cross-project velocity aggregator.

Downloads all public repositories for a GitHub user, computes the median
commit velocity (lines changed per hour) for each project, and outputs
the averaged median velocity across all projects.

Repo sizes are checked via the GitHub API **before** cloning, so oversized
repositories can be skipped without downloading them.

## Usage

```
python3 autofac.py <github-username>
python3 autofac.py <github-username> --max-size=50000   # skip repos > 50 MB
python3 autofac.py <github-username> --cap=72           # cap commit interval at 72h
python3 autofac.py <github-username> --keep             # keep cloned repos
python3 autofac.py <github-username> --include-forks    # include forks
python3 autofac.py <github-username> --token=ghp_...    # use a GitHub token
```

## Options

| Flag | Description |
|---|---|
| `--max-size=KB` | Skip repos larger than this (in KB). 0 = no limit. |
| `--cap=HOURS` | Cap commit-interval hours (default: 168 = 1 week). |
| `--author=NAME` | Filter commits by author name. |
| `--workdir=DIR` | Directory to clone repos into. |
| `--token=TOKEN` | GitHub personal access token (or set `GITHUB_TOKEN` env var). |
| `--include-forks` | Include forked repositories (excluded by default). |
| `--keep` | Keep cloned repos after analysis. |

## How it works

1. Fetches the repo list from GitHub, including the `size` field (KB)
2. Skips repos exceeding `--max-size` **without cloning**
3. Clones each remaining repo and analyzes the full commit history
4. For each non-merge commit interval, computes `velocity = delta / capped_hours`
   where `delta = lines added + removed` and intervals are capped to avoid
   dormant periods diluting the metric
5. Takes the **median** velocity per project
6. Outputs the **mean of medians** across all projects
