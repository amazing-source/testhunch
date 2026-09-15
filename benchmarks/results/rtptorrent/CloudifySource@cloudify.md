### CloudifySource@cloudify

5206 jobs; 5205 evaluated (1 ranked from an empty history are left out), 563 of them failing; 233 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 488 of 563 | 513 of 701 | 34722 of 269620 | 14% |
| 25% | 521 of 563 | 584 of 701 | 73075 of 269620 | 20% |
| 50% | 545 of 563 | 644 of 701 | 160911 of 269620 | 47% |

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
