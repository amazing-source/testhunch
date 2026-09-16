### adamfisk@LittleProxy

581 jobs; 580 evaluated (1 ranked from an empty history are left out), 77 of them failing; 150 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 38 of 77 | 41 of 187 | 3921 of 14753 | 17% |
| 25% | 55 of 77 | 74 of 187 | 5492 of 14753 | 28% |
| 50% | 65 of 77 | 121 of 187 | 8480 of 14753 | 42% |

Mean APFD on the 62 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.910 |
| recently-failed | 0.705 |
| matrix-naive | 0.664 |
| testhunch | 0.661 |
| matrix-conditional-prob | 0.648 |
| random | 0.473 |
| untreated | 0.461 |
