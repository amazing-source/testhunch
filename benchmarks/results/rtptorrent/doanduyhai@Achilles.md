### doanduyhai@Achilles

997 jobs; 995 evaluated (2 ranked from an empty history are left out), 68 of them failing; 224 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 54 of 68 | 190 of 388 | 79262 of 169524 | 11% |
| 25% | 61 of 68 | 289 of 388 | 108825 of 169524 | 24% |
| 50% | 62 of 68 | 346 of 388 | 140217 of 169524 | 47% |

Mean APFD on the 25 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.982 |
| testhunch | 0.794 |
| recently-failed | 0.576 |
| random | 0.527 |
| matrix-naive | 0.480 |
| matrix-conditional-prob | 0.300 |
| untreated | 0.268 |
