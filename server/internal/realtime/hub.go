// Package realtime fans Hub events out to WebSocket clients and SSE streams.
package realtime

import (
	"encoding/json"
	"sync"
)

type subscription struct {
	account string
	ch      chan []byte
}

type Hub struct {
	mu   sync.Mutex
	next int
	subs map[int]subscription
}

func New() *Hub {
	return &Hub{subs: map[int]subscription{}}
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
	h.mu.Lock()
	defer h.mu.Unlock()
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
