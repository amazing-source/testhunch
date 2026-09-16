### jOOQ@jOOQ

3245 jobs; 3242 evaluated (3 ranked from an empty history are left out), 534 of them failing; 79 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 462 of 534 | 476 of 584 | 26751 of 80579 | 17% |
| 25% | 496 of 534 | 514 of 584 | 43773 of 80579 | 30% |
| 50% | 504 of 534 | 530 of 584 | 57373 of 80579 | 49% |

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
