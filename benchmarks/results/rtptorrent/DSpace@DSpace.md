### DSpace@DSpace

3338 jobs; 3332 evaluated (6 ranked from an empty history are left out), 217 of them failing; 1409 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 152 of 217 | 1256 of 3667 | 41117 of 207356 | 15% |
| 25% | 172 of 217 | 2331 of 3667 | 74960 of 207356 | 31% |
| 50% | 203 of 217 | 3123 of 3667 | 128993 of 207356 | 57% |

Mean APFD on the 82 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.822 |
| testhunch | 0.745 |
| recently-failed | 0.714 |
| matrix-naive | 0.562 |
| random | 0.517 |
| matrix-conditional-prob | 0.482 |
| untreated | 0.393 |
