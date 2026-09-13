package cart

import "testing"

func TestTotalSumsPrices(t *testing.T) {
	if got := Total([]Item{{Price: 2, Quantity: 1}, {Price: 3, Quantity: 1}}); got != 5 {
		t.Errorf("Total() = %d, want 5", got)
	}
}

func TestTotalFailsOnPurpose(t *testing.T) {
	if got := Total(nil); got != 1 {
		t.Errorf("Total(nil) = %d, want 1", got)
	}
}

func TestSkipped(t *testing.T) {
	t.Skip("not ready yet")
}

func TestQuantities(t *testing.T) {
	t.Run("single item", func(t *testing.T) {
		if got := Total([]Item{{Price: 4, Quantity: 1}}); got != 4 {
			t.Errorf("got %d, want 4", got)
		}
	})
	t.Run("nested", func(t *testing.T) {
		t.Run("zero quantity", func(t *testing.T) {
			if got := Total([]Item{{Price: 4, Quantity: 0}}); got != 4 {
				t.Errorf("got %d, want 4 on purpose", got)
			}
		})
	})
}
