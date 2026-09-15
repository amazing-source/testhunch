### square@okhttp

9772 jobs; 9771 evaluated (1 ranked from an empty history are left out), 1946 of them failing; 4275 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 1014 of 1946 | 1095 of 2669 | 26234 of 402330 | 8% |
| 25% | 1310 of 1946 | 1511 of 2669 | 49730 of 402330 | 20% |
| 50% | 1561 of 1946 | 1917 of 2669 | 136487 of 402330 | 43% |

Mean APFD on the 778 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.958 |
| recently-failed | 0.917 |
| testhunch | 0.871 |
| matrix-naive | 0.833 |
| matrix-conditional-prob | 0.729 |
| random | 0.494 |
| untreated | 0.490 |
