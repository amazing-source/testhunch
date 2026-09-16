### l0rdn1kk0n@wicket-bootstrap

1110 jobs; 1109 evaluated (1 ranked from an empty history are left out), 414 of them failing; 203 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 401 of 414 | 4213 of 10860 | 18930 of 47491 | 12% |
| 25% | 404 of 414 | 6710 of 10860 | 28024 of 47491 | 27% |
| 50% | 407 of 414 | 9002 of 10860 | 38902 of 47491 | 51% |

Mean APFD on the 342 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.674 |
| testhunch | 0.652 |
| recently-failed | 0.635 |
| matrix-naive | 0.572 |
| random | 0.492 |
| matrix-conditional-prob | 0.488 |
| untreated | 0.331 |
