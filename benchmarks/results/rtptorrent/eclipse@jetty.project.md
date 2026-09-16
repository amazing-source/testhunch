### eclipse@jetty.project

383 jobs; 381 evaluated (2 ranked from an empty history are left out), 316 of them failing; 2 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 267 of 316 | 297 of 384 | 11790 of 58204 | 12% |
| 25% | 303 of 316 | 340 of 384 | 25787 of 58204 | 27% |
| 50% | 310 of 316 | 362 of 384 | 48398 of 58204 | 52% |

Mean APFD on the 325 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.995 |
| testhunch | 0.900 |
| recently-failed | 0.861 |
| random | 0.496 |
| matrix-naive | 0.380 |
| matrix-conditional-prob | 0.265 |
| untreated | 0.181 |
