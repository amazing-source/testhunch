### square@okhttp

9772 jobs; 9771 evaluated (1 ranked from an empty history are left out), 1946 of them failing; 4275 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 1095 of 1946 | 1200 of 2669 | 142591 of 402330 | 11% |
| 25% | 1413 of 1946 | 1677 of 2669 | 206370 of 402330 | 25% |
| 50% | 1673 of 1946 | 2132 of 2669 | 294609 of 402330 | 48% |

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
