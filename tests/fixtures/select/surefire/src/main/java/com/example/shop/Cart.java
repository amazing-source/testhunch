package com.example.shop;

public final class Cart {
    private Cart() {}

    public static int total(int... prices) {
        int total = 0;
        for (int price : prices) {
            total += price;
        }
        return total;
    }
}
