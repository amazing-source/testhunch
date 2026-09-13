package com.example.shop;

import static org.junit.jupiter.api.Assertions.fail;

import org.junit.jupiter.api.Test;

class FlakyTest {
    private static int failures = 0;
    private static int errors = 0;

    // Each fails the first time and passes when Surefire reruns it in the same JVM: one with an
    // assertion (<flakyFailure>), one with an unexpected exception (<flakyError>).
    @Test
    void failsOnFirstAttempt() {
        if (failures++ == 0) {
            fail("first attempt fails on purpose");
        }
    }

    @Test
    void throwsOnFirstAttempt() {
        if (errors++ == 0) {
            throw new IllegalStateException("first attempt throws on purpose");
        }
    }
}
