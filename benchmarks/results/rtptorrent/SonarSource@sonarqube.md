### SonarSource@sonarqube

53307 jobs; 53305 evaluated (2 ranked from an empty history are left out), 3131 of them failing; 32321 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 2498 of 3131 | 6143 of 10766 | 2599675 of 17089930 | 41% |
| 25% | 2649 of 3131 | 7504 of 10766 | 5561910 of 17089930 | 48% |
| 50% | 2813 of 3131 | 8790 of 10766 | 10970556 of 17089930 | 61% |

Mean APFD on the 618 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.859 |
| testhunch | 0.801 |
| recently-failed | 0.753 |
| matrix-naive | 0.621 |
| matrix-conditional-prob | 0.529 |
| random | 0.495 |
| untreated | 0.284 |
