### brettwooldridge@HikariCP

1662 jobs; 1659 evaluated (3 ranked from an empty history are left out), 94 of them failing; 85 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 59 of 94 | 135 of 263 | 10609 of 23690 | 13% |
| 25% | 68 of 94 | 172 of 263 | 13186 of 23690 | 26% |
| 50% | 80 of 94 | 204 of 263 | 16988 of 23690 | 49% |

Mean APFD on the 125 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.902 |
| testhunch | 0.741 |
| recently-failed | 0.710 |
| matrix-naive | 0.664 |
| matrix-conditional-prob | 0.640 |
| untreated | 0.611 |
| random | 0.477 |
