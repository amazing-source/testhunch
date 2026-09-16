### julianhyde@optiq

1808 jobs; 1806 evaluated (2 ranked from an empty history are left out), 130 of them failing; 502 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 70 of 130 | 93 of 174 | 38667 of 78056 | 14% |
| 25% | 95 of 130 | 120 of 174 | 48379 of 78056 | 26% |
| 50% | 123 of 130 | 161 of 174 | 65583 of 78056 | 49% |

Mean APFD on the 68 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.866 |
| testhunch | 0.771 |
| recently-failed | 0.723 |
| random | 0.532 |
| matrix-naive | 0.458 |
| matrix-conditional-prob | 0.262 |
| untreated | 0.188 |
