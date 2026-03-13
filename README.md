# autofac

autofac measures how fast code changes across a developer's public GitHub
projects. It clones every non-fork repository for a given user, computes a
median commit velocity for each project, and averages the results into a single
number: **lines per hour**.

## How velocity is calculated

For each repository, autofac walks the commit history (excluding merges) and
looks at consecutive pairs of commits. For each pair it records:

- **Lines changed** — the sum of lines added and lines removed
  (`git diff --numstat`).
- **Time elapsed** — the gap in seconds between the two commit timestamps.

Dividing lines changed by hours elapsed gives a velocity for that interval. The
per-project result is the **median** of all such interval velocities. The
cross-project result is the **mean** of those medians.

$$v_i = \frac{\Delta L_i}{\Delta t_i} \qquad V_{\text{project}} = \operatorname{median}(v_1, v_2, \ldots, v_n) \qquad V = \frac{1}{P}\sum_{p=1}^{P} V_p$$

where $\Delta L_i$ is lines added + removed in interval $i$, $\Delta t_i$ is
the elapsed time in hours, and $P$ is the number of projects with nonzero
velocity.

Intervals where the time gap is zero or negative are dropped (they'd produce
infinite or meaningless values). Repos that yield zero velocity — no measurable
output over time — are excluded from the final average entirely, so they don't
drag the aggregate toward zero.

### Why the median

Commit histories are noisy. A developer might push a one-line typo fix seconds
after a large refactor, or disappear for a month and return with a single
commit. The median absorbs these outliers without distorting the picture the way
an arithmetic mean would. It answers the question: *on a typical working
interval, how many lines per hour were changing?*

### What it doesn't capture

Velocity in lines per hour is deliberately crude. It says nothing about the
quality, complexity, or impact of the changes. A thousand lines of generated
code count the same as ten lines of careful algorithm work. And because it
relies on commit timestamps rather than actual working time, long gaps between
commits (vacations, context switches, waiting on review) inflate the
denominator and deflate the number.

The `--cap` flag exists to partially address this: it clamps the maximum
interval between two commits, so that a two-week vacation doesn't count as two
weeks of slow coding. A reasonable cap (say, 72 hours) makes the metric more
reflective of active development periods, though choosing the right value is
inherently subjective.

## Usage

### autofac (cross-project aggregator)

```
python3 autofac.py <github-username>
```

Clones all public, non-fork repos for the user, computes per-project median
velocity, and prints the averaged result.

Options:

```
--max-size=50       Skip repos larger than 50 MB (default: 25, checked via API before cloning)
--cap=72            Cap commit intervals at 72 hours
--author="Jane"     Only count commits by a specific author
--exclude-author="bot"  Exclude commits by author (comma-separated, substring match)
--max-velocity=5000 Discard intervals above this velocity in lines/hour (0 = disabled, default: 100)
--machine           Machine-assisted mode (sets --max-velocity default to 10000)
--keep              Keep cloned repos on disk after analysis
--dry               Estimate max disk usage without cloning anything
--workdir=/tmp/af   Clone into a custom directory (default: ./autofac_work)
--token=ghp_...     GitHub personal access token (or set GITHUB_TOKEN env var)
```

`--dry` is useful before a large run. Combined with `--keep` it reports the
total size of all repos that would be retained; without `--keep` it reports
the size of the largest single repo (since repos are cloned and deleted one at
a time).

### core.py (single-repo analysis)

`median_velocity` can be used directly on any local git repository:

```python
from core import median_velocity

vel = median_velocity("/path/to/repo", cap_hours=72, author="Jane")
if vel is not None:
    print(f"{vel:.1f} lines/hour")
```

Returns `None` if the repo has fewer than two qualifying commits, or if no
intervals produced a measurable velocity.

## Interpreting the modes

- `autofac.py --machine` — roughly approximates AI-assisted velocity
- `autofac.py` (default) — roughly approximates personal velocity
  (unless your repos contain many foreign commits)
