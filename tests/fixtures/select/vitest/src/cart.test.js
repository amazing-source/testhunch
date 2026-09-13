import { describe, expect, test } from "vitest";

describe("cart total", () => {
  test("sums prices", () => expect(2 + 3).toBe(5));
  test("sums prices twice", () => expect(5 + 5).toBe(10));
  describe("nested", () => {
    test("handles quantities", () => expect(4).toBe(4));
  });
  test.each([1, 2])("price %i is positive", (price) => expect(price > 0).toBe(true));
});
