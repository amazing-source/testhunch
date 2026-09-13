package com.example.shop;

import static org.junit.jupiter.api.Assertions.fail;

import org.junit.jupiter.api.Test;

class FlakyTest {
    private static int attempts = 0;

    // Fails the first time, passes when Surefire reruns it in the same JVM.
    @Test
    void failsOnFirstAttempt() {
        if (attempts++ == 0) {
            fail("first attempt fails on purpose");
        }
    }
}
