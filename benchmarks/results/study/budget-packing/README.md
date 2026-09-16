# What a budget does with a test that does not fit

Three rules, replayed side by side on the **same** rankings: only what happens at the
first test too expensive to fit differs between the columns.

- **prefix**: stop there. The order is what the ranking promises, and nothing below a
  left-out test ever runs.
- **oversized**: pass over a test that could not have fitted in the whole budget however
  early it came, and stop at any other test that does not fit.
- **fill**: keep going past everything that does not fit, to the end of the ranking.

10 projects, 30944 jobs with a usable ranking.

Failing jobs that stay red, and the share of test time spent, per budget:

| Budget | Rule | Failing jobs caught | Failing tests run | Test time spent |
|---|---|---:|---:|---:|
| 10% | prefix | 70.4% | 63.0% | 12.6% |
| 10% | oversized | 71.2% | 64.5% | 13.1% |
| 10% | fill | 73.2% | 66.3% | 13.8% |
| 25% | prefix | 80.9% | 75.1% | 29.4% |
| 25% | oversized | 81.6% | 76.4% | 29.7% |
| 25% | fill | 84.3% | 79.4% | 30.8% |
| 50% | prefix | 88.7% | 85.5% | 53.9% |
| 50% | oversized | 89.2% | 85.9% | 54.2% |
| 50% | fill | 91.6% | 88.9% | 55.2% |

A rule that catches more failing jobs while spending more time has not necessarily won:
the budget is what a user asked to spend, and a rule that spends more of it is not
cheating, it is doing what was asked. So the comparison that decides is at equal time.

## At equal time

`prefix` measured at three budgets gives a curve of failing jobs caught against test time
spent. Each other rule is placed on that curve at **its own** time cost, by linear
interpolation, and the column is what it catches beyond a prefix that spends the same.

| Budget | Rule | Test time spent | Caught | `prefix` at that time | Difference |
|---|---|---:|---:|---:|---:|
| 10% | oversized | 13.1% | 71.2% | 70.7% | +0.5 pt |
| 10% | fill | 13.8% | 73.2% | 71.1% | +2.0 pt |
| 25% | oversized | 29.7% | 81.6% | 81.0% | +0.6 pt |
| 25% | fill | 30.8% | 84.3% | 81.4% | +3.0 pt |
| 50% | oversized | 54.2% | 89.2% | 88.8% | +0.5 pt |
| 50% | fill | 55.2% | 91.6% | 89.1% | +2.6 pt |
