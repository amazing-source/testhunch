### thinkaurelius@titan

1075 jobs; 1074 evaluated (1 ranked from an empty history are left out), 280 of them failing; 134 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 158 of 280 | 277 of 660 | 3948 of 45038 | 8% |
| 25% | 230 of 280 | 404 of 660 | 7357 of 45038 | 24% |
| 50% | 255 of 280 | 546 of 660 | 14379 of 45038 | 50% |

Mean APFD on the 254 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.970 |
| testhunch | 0.829 |
| recently-failed | 0.785 |
| random | 0.493 |
| matrix-naive | 0.459 |
| matrix-conditional-prob | 0.362 |
| untreated | 0.258 |
