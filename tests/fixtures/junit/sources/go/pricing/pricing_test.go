package pricing

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDiscount(t *testing.T) {
	if got := 100 * 90 / 100; got != 90 {
		t.Errorf("got %d, want 90", got)
	}
}

// Fails the first time it runs in a report, passes when gotestsum reruns it.
func TestFlakyFirstAttempt(t *testing.T) {
	marker := filepath.Join(os.Getenv("FLAKY_STATE_DIR"), "attempted")
	if _, err := os.Stat(marker); err != nil {
		if err := os.WriteFile(marker, nil, 0o600); err != nil {
			t.Fatal(err)
		}
		t.Fatal("first attempt fails on purpose")
	}
}
