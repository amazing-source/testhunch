#[test]
fn checkout_total() {
    assert_eq!(shop::total(&[1, 1]), 2);
}
