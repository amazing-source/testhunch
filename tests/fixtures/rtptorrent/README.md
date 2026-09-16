# RTPTorrent extract

`adamfisk@LittleProxy/` holds the rows of the first 80 Travis jobs (by job id, 1053609 to 6199329)
of the LittleProxy project in RTPTorrent, in the layout `benchmarks/rtptorrent/data.py` writes to its
cache: the project's results, the job to commit rows of `tr_all_built_commits.csv` for those jobs,
the patches of those commits, the offenders among those jobs, and the baseline schedules' rows for
those jobs. The rows are copied unchanged.

Source: T. Mattis, P. Rein, F. Dürsch and R. Hirschfeld, "RTPTorrent: An Open-source Dataset for
Evaluating Regression Test Prioritization", MSR 2020, doi:10.1145/3379597.3387458. Dataset version
1.1, doi:10.5281/zenodo.4046180, licensed under Creative Commons Attribution 4.0 International
(https://creativecommons.org/licenses/by/4.0/). The extract selects rows; it does not modify them.

**Every test that needs this project must read it from here**, never through `fetch_project`, which
downloads the real dataset over the network. One test did, and it cost 69 of the suite's 89 seconds
in CI, on every run, for rows that are already in this directory.
