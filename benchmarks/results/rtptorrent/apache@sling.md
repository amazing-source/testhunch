### apache@sling

8552 jobs; 1502 evaluated (7050 ranked from an empty history are left out), 846 of them failing; 7149 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 757 of 846 | 895 of 1195 | 167501 of 282811 | 12% |
| 25% | 812 of 846 | 1079 of 1195 | 204199 of 282811 | 29% |
| 50% | 833 of 846 | 1173 of 1195 | 241078 of 282811 | 51% |

Mean APFD on the 812 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.996 |
| testhunch | 0.973 |
| recently-failed | 0.964 |
| random | 0.503 |
| matrix-naive | 0.365 |
| matrix-conditional-prob | 0.263 |
| untreated | 0.009 |
