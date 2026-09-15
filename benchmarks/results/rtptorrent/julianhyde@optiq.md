### julianhyde@optiq

1808 jobs; 1806 evaluated (2 ranked from an empty history are left out), 130 of them failing; 502 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 62 of 130 | 74 of 174 | 9367 of 78056 | 10% |
| 25% | 89 of 130 | 104 of 174 | 12745 of 78056 | 17% |
| 50% | 104 of 130 | 140 of 174 | 32394 of 78056 | 41% |

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
