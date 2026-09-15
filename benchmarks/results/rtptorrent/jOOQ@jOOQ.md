### jOOQ@jOOQ

3245 jobs; 3242 evaluated (3 ranked from an empty history are left out), 534 of them failing; 79 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 460 of 534 | 471 of 584 | 9760 of 80579 | 15% |
| 25% | 486 of 534 | 501 of 584 | 19621 of 80579 | 25% |
| 50% | 500 of 534 | 526 of 584 | 50601 of 80579 | 48% |

Mean APFD on the 523 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.979 |
| recently-failed | 0.922 |
| testhunch | 0.852 |
| matrix-naive | 0.690 |
| matrix-conditional-prob | 0.544 |
| random | 0.509 |
| untreated | 0.242 |
