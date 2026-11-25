package realtime

import (
	"sync"
	"testing"
)

func TestPublishSeqAssignedUnderRingLock(t *testing.T) {
	h := New()
	const n = 200
	var wg sync.WaitGroup
	wg.Add(n)
	for i := 0; i < n; i++ {
		go func(i int) {
			defer wg.Done()
			h.Publish("acc", "job", map[string]any{"i": i})
		}(i)
	}
	wg.Wait()

	if h.CurrentSeq() != int64(n) {
		t.Fatalf("CurrentSeq=%d want %d", h.CurrentSeq(), n)
	}
	// Ring retains the newest ringCap events; they must be strictly increasing
	// and contiguous so poll cursors cannot skip a lower seq that lands later.
	events := h.Recent("acc", 0, h.ringCap+10)
	if len(events) != h.ringCap {
		t.Fatalf("want %d ring events, got %d", h.ringCap, len(events))
	}
	wantStart := int64(n - h.ringCap + 1)
	for i, ev := range events {
		want := wantStart + int64(i)
		if ev.Seq != want {
			t.Fatalf("ring order vs seq broken at %d: got seq=%d want=%d", i, ev.Seq, want)
		}
	}
}

func TestEpochUniquePerHub(t *testing.T) {
	a := New()
	b := New()
	if a.Epoch() == "" || b.Epoch() == "" {
		t.Fatal("epoch must be non-empty")
	}
	if a.Epoch() == b.Epoch() {
		t.Fatalf("epochs collided: %s", a.Epoch())
	}
}

func TestRecentRespectsAfterSeq(t *testing.T) {
	h := New()
	h.Publish("acc", "a", map[string]any{"n": 1})
	h.Publish("acc", "b", map[string]any{"n": 2})
	h.Publish("acc", "c", map[string]any{"n": 3})
	got := h.Recent("acc", 2, 10)
	if len(got) != 1 || got[0].Seq != 3 || got[0].Event != "c" {
		t.Fatalf("unexpected recent: %+v", got)
	}
}
