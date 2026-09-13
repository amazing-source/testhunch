pub fn total(prices: &[u32]) -> u32 {
    prices.iter().sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sums_prices() {
        assert_eq!(total(&[2, 3]), 5);
    }

    #[test]
    fn fails_on_purpose() {
        assert_eq!(total(&[]), 1, "empty cart on purpose");
    }

    #[test]
    #[ignore = "not ready yet"]
    fn ignored_case() {}

    #[test]
    #[should_panic(expected = "on purpose")]
    fn panics_as_expected() {
        panic!("on purpose");
    }

    // Fails the first time it runs, passes when nextest retries it. Each attempt is a new
    // process, so the state lives in a file.
    #[test]
    fn flaky_first_attempt() {
        let marker = std::path::Path::new(&std::env::var("FLAKY_STATE_DIR").unwrap()).join("attempted");
        if !marker.exists() {
            std::fs::write(&marker, b"").unwrap();
            panic!("first attempt fails on purpose");
        }
    }

    mod nested {
        #[test]
        fn keeps_total_for_one_item() {
            assert_eq!(super::total(&[4]), 4);
        }
    }
}
