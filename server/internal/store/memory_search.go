package store

import (
	"context"
	"fmt"
	"regexp"
	"strings"
)

// MemoryQuery is the recall filter. Q is matched with Postgres full-text
// search using the same tokens as the Python hub (up to eight words).
type MemoryQuery struct {
	AccountID string
	Pod       string
	Pods      []string
	Kind      string
	JobID     string
	Company   string
	Q         string
	Now       string
	Limit     int
}

var memoryToken = regexp.MustCompile(`[A-Za-z0-9_]{2,}`)

// MemoryFTS turns a recall string into a simple-config tsquery.
// An empty result means the caller asked for no text filter.
func MemoryFTS(raw string) string {
	tokens := memoryToken.FindAllString(raw, 8)
	if len(tokens) == 0 {
		return ""
	}
	for i, tok := range tokens {
		tokens[i] = strings.ToLower(tok)
	}
	return strings.Join(tokens, " & ")
}

func memorySearchSQL(q MemoryQuery) (string, []any) {
	sql := memorySelect + ` WHERE account_id=$1 AND (expires_at='' OR pinned OR expires_at > $2)`
	args := []any{q.AccountID, q.Now}
	add := func(v any) string {
		args = append(args, v)
		return fmt.Sprintf("$%d", len(args))
	}
	if q.Pod != "" {
		sql += ` AND (pod=` + add(q.Pod) + ` OR pod LIKE ` + add(q.Pod+":%") + `)`
	} else if len(q.Pods) > 0 {
		sql += ` AND pod = ANY(` + add(q.Pods) + `)`
	}
	if q.Kind != "" {
		sql += ` AND kind=` + add(strings.ToLower(strings.TrimSpace(q.Kind)))
	}
	if q.JobID != "" {
		sql += ` AND job_id=` + add(strings.TrimSpace(q.JobID))
	}
	if q.Company != "" {
		sql += ` AND lower(company)=lower(` + add(strings.TrimSpace(q.Company)) + `)`
	}
	if fts := MemoryFTS(q.Q); fts != "" {
		sql += ` AND to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(body,'') || ' ' || coalesce(company,'')) @@ to_tsquery('simple', ` + add(fts) + `)`
	}
	limit := q.Limit
	if limit <= 0 {
		limit = 12
	}
	sql += ` ORDER BY pinned DESC, importance DESC, updated_at DESC LIMIT ` + add(limit)
	return sql, args
}

func (p *Postgres) SearchMemory(ctx context.Context, q MemoryQuery) ([]MemoryItem, error) {
	sql, args := memorySearchSQL(q)
	rows, err := p.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []MemoryItem
	for rows.Next() {
		item, err := scanMemory(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}
