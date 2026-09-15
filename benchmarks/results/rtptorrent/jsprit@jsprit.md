### jsprit@jsprit

1089 jobs; 1085 evaluated (4 ranked from an empty history are left out), 59 of them failing; 28 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 50 of 59 | 70 of 135 | 31916 of 93445 | 9% |
| 25% | 54 of 59 | 74 of 135 | 67408 of 93445 | 22% |
| 50% | 54 of 59 | 118 of 135 | 81545 of 93445 | 43% |

Mean APFD on the 51 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.986 |
| testhunch | 0.843 |
| recently-failed | 0.624 |
| matrix-naive | 0.610 |
| random | 0.539 |
| matrix-conditional-prob | 0.521 |
| untreated | 0.473 |
