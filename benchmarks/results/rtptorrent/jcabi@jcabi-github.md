### jcabi@jcabi-github

3241 jobs; 3240 evaluated (1 ranked from an empty history are left out), 429 of them failing; 931 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 342 of 429 | 475 of 735 | 49644 of 444632 | 12% |
| 25% | 374 of 429 | 560 of 735 | 116596 of 444632 | 29% |
| 50% | 395 of 429 | 641 of 735 | 284706 of 444632 | 55% |

Mean APFD on the 337 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.849 |
| recently-failed | 0.719 |
| testhunch | 0.676 |
| random | 0.507 |
| matrix-naive | 0.472 |
| matrix-conditional-prob | 0.460 |
| untreated | 0.294 |
