package billing

import "testing"

// Same name as a test in package cart: skipping one by name would skip both.
func TestTotalSumsPrices(t *testing.T) {}

func TestInvoice(t *testing.T) {
	t.Run("single item", func(t *testing.T) {})
	t.Run("two items", func(t *testing.T) {})
}
