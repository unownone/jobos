// Package cache is the hot-path seam. Production points REDIS_URL at Redis.
// An empty URL selects the nop driver so a single small Hub still runs.
package cache

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

type Cache interface {
	Name() string
	Get(ctx context.Context, key string) ([]byte, bool, error)
	Set(ctx context.Context, key string, value []byte, ttl time.Duration) error
	DeletePrefix(ctx context.Context, prefix string) error
}

type Nop struct{}

func (Nop) Name() string                                             { return "none" }
func (Nop) Get(context.Context, string) ([]byte, bool, error)        { return nil, false, nil }
func (Nop) Set(context.Context, string, []byte, time.Duration) error { return nil }
func (Nop) DeletePrefix(context.Context, string) error               { return nil }

type Memory struct {
	mu    sync.Mutex
	items map[string]memItem
}

type memItem struct {
	value []byte
	exp   time.Time
}

func NewMemory() *Memory { return &Memory{items: map[string]memItem{}} }

func (m *Memory) Name() string { return "memory" }

func (m *Memory) Get(_ context.Context, key string) ([]byte, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	item, ok := m.items[key]
	if !ok {
		return nil, false, nil
	}
	if !item.exp.IsZero() && time.Now().After(item.exp) {
		delete(m.items, key)
		return nil, false, nil
	}
	return append([]byte(nil), item.value...), true, nil
}

func (m *Memory) Set(_ context.Context, key string, value []byte, ttl time.Duration) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	var exp time.Time
	if ttl > 0 {
		exp = time.Now().Add(ttl)
	}
	m.items[key] = memItem{value: append([]byte(nil), value...), exp: exp}
	return nil
}

func (m *Memory) DeletePrefix(_ context.Context, prefix string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for k := range m.items {
		if strings.HasPrefix(k, prefix) {
			delete(m.items, k)
		}
	}
	return nil
}

type Redis struct {
	client *redis.Client
}

func NewRedis(url string) (*Redis, error) {
	opt, err := redis.ParseURL(url)
	if err != nil {
		return nil, err
	}
	return &Redis{client: redis.NewClient(opt)}, nil
}

func (r *Redis) Name() string { return "redis" }

func (r *Redis) Get(ctx context.Context, key string) ([]byte, bool, error) {
	b, err := r.client.Get(ctx, key).Bytes()
	if err == redis.Nil {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	return b, true, nil
}

func (r *Redis) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	return r.client.Set(ctx, key, value, ttl).Err()
}

func (r *Redis) DeletePrefix(ctx context.Context, prefix string) error {
	var cursor uint64
	for {
		keys, next, err := r.client.Scan(ctx, cursor, prefix+"*", 100).Result()
		if err != nil {
			return err
		}
		if len(keys) > 0 {
			if err := r.client.Del(ctx, keys...).Err(); err != nil {
				return err
			}
		}
		cursor = next
		if cursor == 0 {
			return nil
		}
	}
}

func Open(redisURL, driver string) (Cache, error) {
	if strings.TrimSpace(redisURL) != "" {
		return NewRedis(redisURL)
	}
	switch strings.ToLower(strings.TrimSpace(driver)) {
	case "memory", "mem":
		return NewMemory(), nil
	default:
		return Nop{}, nil
	}
}
