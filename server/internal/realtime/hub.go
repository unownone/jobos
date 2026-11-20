// Package realtime fans Hub events out to WebSocket clients and SSE streams.
package realtime

import (
	"encoding/json"
	"sync"
)

type Hub struct {
	mu   sync.Mutex
	next int
	subs map[int]chan []byte
}

func New() *Hub {
	return &Hub{subs: map[int]chan []byte{}}
}

func (h *Hub) Subscribe() (int, <-chan []byte) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.next++
	id := h.next
	ch := make(chan []byte, 16)
	h.subs[id] = ch
	return id, ch
}

func (h *Hub) Unsubscribe(id int) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if ch, ok := h.subs[id]; ok {
		delete(h.subs, id)
		close(ch)
	}
}

func (h *Hub) Publish(event string, payload any) {
	body, err := json.Marshal(map[string]any{"event": event, "data": payload})
	if err != nil {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, ch := range h.subs {
		select {
		case ch <- body:
		default:
		}
	}
}
