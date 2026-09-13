package com.example.shop;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class CartTest {
    @Test
    void sumsPrices() {
        assertEquals(5, Cart.total(2, 3));
    }

    @Test
    void sumsPricesTwice() {
        assertEquals(10, Cart.total(5, 5));
    }

    @Test
    void failsOnPurpose() {
        assertEquals(1, Cart.total(), "empty cart on purpose");
    }

    @Test
    void throwsUnexpectedly() {
        throw new IllegalStateException("boom on purpose");
    }

    @Test
    @Disabled("not ready yet")
    void skippedCase() {}

    @ParameterizedTest
    @ValueSource(ints = {1, 2})
    void priceIsOdd(int price) {
        assertTrue(Cart.total(price) % 2 == 1, "even price on purpose");
    }

    @Nested
    class Discounts {
        @Test
        void keepsTotalWithoutDiscount() {
            assertEquals(4, Cart.total(4));
        }
    }
}
