// Package realtime fans Hub events out to WebSocket clients and SSE streams.
package realtime

import (
	"encoding/json"
	"sync"
	"sync/atomic"
)

type subscription struct {
	account string
	ch      chan []byte
}

// Event is a buffered Hub fan-out frame with a monotonic sequence for MCP poll.
type Event struct {
	Seq     int64  `json:"seq"`
	Event   string `json:"event"`
	Data    any    `json:"data"`
	RawJSON []byte `json:"-"`
}

type Hub struct {
	mu      sync.Mutex
	next    int
	subs    map[int]subscription
	seq     atomic.Int64
	recent  map[string][]Event
	ringCap int
}

func New() *Hub {
	return &Hub{subs: map[int]subscription{}, recent: map[string][]Event{}, ringCap: 128}
}

func (h *Hub) Subscribe(account string) (int, <-chan []byte) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.next++
	id := h.next
	ch := make(chan []byte, 16)
	h.subs[id] = subscription{account: account, ch: ch}
	return id, ch
}

func (h *Hub) Unsubscribe(id int) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if sub, ok := h.subs[id]; ok {
		delete(h.subs, id)
		close(sub.ch)
	}
}

func (h *Hub) Publish(account, event string, payload any) {
	body, err := json.Marshal(map[string]any{"event": event, "data": payload})
	if err != nil {
		return
	}
	seq := h.seq.Add(1)
	ev := Event{Seq: seq, Event: event, Data: payload, RawJSON: body}
	h.mu.Lock()
	defer h.mu.Unlock()
	ring := append(h.recent[account], ev)
	if len(ring) > h.ringCap {
		ring = ring[len(ring)-h.ringCap:]
	}
	h.recent[account] = ring
	for _, sub := range h.subs {
		if sub.account != account {
			continue
		}
		select {
		case sub.ch <- body:
		default:
		}
	}
}

// Recent returns buffered events with Seq greater than afterSeq (exclusive).
// MCP agents use this instead of holding a WebSocket.
func (h *Hub) Recent(account string, afterSeq int64, limit int) []Event {
	if limit <= 0 {
		limit = 32
	}
	if limit > 128 {
		limit = 128
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	ring := h.recent[account]
	out := make([]Event, 0, limit)
	for _, ev := range ring {
		if ev.Seq <= afterSeq {
			continue
		}
		out = append(out, ev)
		if len(out) >= limit {
			break
		}
	}
	return out
}
