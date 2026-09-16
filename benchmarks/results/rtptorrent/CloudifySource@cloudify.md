### CloudifySource@cloudify

5206 jobs; 5205 evaluated (1 ranked from an empty history are left out), 563 of them failing; 233 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 494 of 563 | 526 of 701 | 89318 of 269620 | 17% |
| 25% | 527 of 563 | 600 of 701 | 138182 of 269620 | 27% |
| 50% | 546 of 563 | 649 of 701 | 198901 of 269620 | 49% |

Mean APFD on the 496 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.979 |
| recently-failed | 0.918 |
| testhunch | 0.891 |
| matrix-naive | 0.762 |
| matrix-conditional-prob | 0.712 |
| random | 0.500 |
| untreated | 0.214 |
