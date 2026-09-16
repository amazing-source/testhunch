### thinkaurelius@titan

1075 jobs; 1074 evaluated (1 ranked from an empty history are left out), 280 of them failing; 134 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 170 of 280 | 316 of 660 | 17514 of 45038 | 12% |
| 25% | 239 of 280 | 449 of 660 | 22710 of 45038 | 28% |
| 50% | 258 of 280 | 576 of 660 | 28850 of 45038 | 53% |

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
