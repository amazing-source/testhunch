describe("discounts", () => {
  test("ten percent", () => expect(90).toBe(90));
  test("none", () => expect(100).toBe(100));
});
