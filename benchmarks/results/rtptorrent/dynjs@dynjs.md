### dynjs@dynjs

1020 jobs; 1018 evaluated (2 ranked from an empty history are left out), 55 of them failing; 85 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 43 of 55 | 285 of 510 | 15859 of 72576 | 8% |
| 25% | 43 of 55 | 346 of 510 | 23709 of 72576 | 17% |
| 50% | 46 of 55 | 429 of 510 | 36516 of 72576 | 31% |

Mean APFD on the 41 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.911 |
| testhunch | 0.738 |
| recently-failed | 0.653 |
| matrix-naive | 0.565 |
| random | 0.515 |
| matrix-conditional-prob | 0.511 |
| untreated | 0.400 |
