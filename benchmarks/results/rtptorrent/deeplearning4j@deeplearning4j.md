### deeplearning4j@deeplearning4j

1038 jobs; 1037 evaluated (1 ranked from an empty history are left out), 585 of them failing; 56 jobs have no known changed files.

| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |
|---:|---:|---:|---:|---:|
| 10% | 537 of 585 | 708 of 930 | 8188 of 14700 | 18% |
| 25% | 563 of 585 | 758 of 930 | 10636 of 14700 | 29% |
| 50% | 570 of 585 | 831 of 930 | 12503 of 14700 | 44% |

Mean APFD on the 566 jobs the authors' schedules cover. It counts every class with a failing row, as their schedules do, where the table above leaves out the flaky ones (docs/adr/0006): the two are not over the same jobs.

| Schedule | Mean APFD |
|---|---:|
| optimal-failure | 0.925 |
| testhunch | 0.871 |
| recently-failed | 0.862 |
| matrix-naive | 0.768 |
| matrix-conditional-prob | 0.657 |
| untreated | 0.496 |
| random | 0.490 |
