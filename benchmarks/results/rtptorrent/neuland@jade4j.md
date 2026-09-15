### neuland@jade4j

932 jobs; 931 evaluated (1 ranked from an empty history are left out), 96 of them failing; 1 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 87 of 96 | 1050 of 1323 | 9152 of 30887 | 51% |
| 25% | 92 of 96 | 1112 of 1323 | 14804 of 30887 | 73% |
| 50% | 92 of 96 | 1167 of 1323 | 15829 of 30887 | 81% |

Mean APFD on the 96 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.822 |
| recently-failed | 0.752 |
| testhunch | 0.713 |
| matrix-naive | 0.705 |
| matrix-conditional-prob | 0.613 |
| untreated | 0.516 |
| random | 0.515 |
