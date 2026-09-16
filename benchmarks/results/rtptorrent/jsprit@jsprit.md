### jsprit@jsprit

1089 jobs; 1085 evaluated (4 ranked from an empty history are left out), 59 of them failing; 28 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 50 of 59 | 102 of 135 | 39878 of 93445 | 10% |
| 25% | 58 of 59 | 130 of 135 | 78218 of 93445 | 24% |
| 50% | 58 of 59 | 126 of 135 | 89105 of 93445 | 45% |

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
