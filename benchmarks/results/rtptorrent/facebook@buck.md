### facebook@buck

1148 jobs; 1146 evaluated (2 ranked from an empty history are left out), 477 of them failing; 293 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 451 of 477 | 1984 of 2267 | 426964 of 759247 | 10% |
| 25% | 460 of 477 | 2197 of 2267 | 529043 of 759247 | 26% |
| 50% | 472 of 477 | 2240 of 2267 | 720358 of 759247 | 51% |

Mean APFD on the 341 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.987 |
| recently-failed | 0.964 |
| testhunch | 0.936 |
| matrix-naive | 0.748 |
| matrix-conditional-prob | 0.570 |
| random | 0.492 |
| untreated | 0.485 |
