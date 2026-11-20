package store

import (
	"context"
	"strings"
	"sync"
)

type Memory struct {
	mu         sync.Mutex
	accounts   map[string]Account
	userByName map[string]string
	adminByAcc map[string]string
	users      map[string]User
	sessions   map[string]Session
	sessByHash map[string]string
	keys       map[string]APIKey
	keyByHash  map[string]string
	invites    map[string]Invite
	jobs       map[string]Job
	events     []Event
	eventSeq   int64
	queue      map[string]QueueItem
	people     map[string]Person
	memory     map[string]MemoryItem
	messages   map[string]Message
	skills     map[string]Skill
	mcps       map[string]MCP
	records    map[string]Recording
	presence   map[string]Presence
	burns      []Burn
	burnSeq    int64
	peers      map[string]Peer
	tasks      []Task
	kv         map[string]string
}

func NewMemory() *Memory {
	return &Memory{
		accounts:   map[string]Account{},
		userByName: map[string]string{},
		adminByAcc: map[string]string{},
		users:      map[string]User{},
		sessions:   map[string]Session{},
		sessByHash: map[string]string{},
		keys:       map[string]APIKey{},
		keyByHash:  map[string]string{},
		invites:    map[string]Invite{},
		jobs:       map[string]Job{},
		queue:      map[string]QueueItem{},
		people:     map[string]Person{},
		memory:     map[string]MemoryItem{},
		messages:   map[string]Message{},
		skills:     map[string]Skill{},
		mcps:       map[string]MCP{},
		records:    map[string]Recording{},
		presence:   map[string]Presence{},
		peers:      map[string]Peer{},
		kv:         map[string]string{},
	}
}

func (m *Memory) Name() string               { return "memory" }
func (m *Memory) Ping(context.Context) error { return nil }
func (m *Memory) Close() error               { return nil }

func jobKey(account, id string) string { return account + "\x00" + id }

func (m *Memory) CreateAccount(_ context.Context, a Account, admin User) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	name := strings.ToLower(a.Username)
	if _, ok := m.userByName[name]; ok {
		return ErrConflict
	}
	m.accounts[a.ID] = a
	m.users[admin.ID] = admin
	m.userByName[name] = admin.ID
	m.adminByAcc[a.ID] = admin.ID
	return nil
}

func (m *Memory) AccountByUsername(_ context.Context, username string) (Account, User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	uid, ok := m.userByName[strings.ToLower(username)]
	if !ok {
		return Account{}, User{}, ErrNotFound
	}
	u := m.users[uid]
	a, ok := m.accounts[u.AccountID]
	if !ok {
		return Account{}, User{}, ErrNotFound
	}
	return a, u, nil
}

func (m *Memory) CreateUser(_ context.Context, u User) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.users[u.ID]; ok {
		return ErrConflict
	}
	m.users[u.ID] = u
	return nil
}

func (m *Memory) User(_ context.Context, id string) (User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	u, ok := m.users[id]
	if !ok {
		return User{}, ErrNotFound
	}
	return u, nil
}

func (m *Memory) ListUsers(_ context.Context, accountID, kind, track string) ([]User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []User
	for _, u := range m.users {
		if u.AccountID != accountID {
			continue
		}
		if kind != "" && u.Kind != kind {
			continue
		}
		if track != "" && u.Track != track {
			continue
		}
		out = append(out, u)
	}
	return out, nil
}

func (m *Memory) SaveUser(_ context.Context, u User) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.users[u.ID]; !ok {
		return ErrNotFound
	}
	m.users[u.ID] = u
	return nil
}

func (m *Memory) CreateSession(_ context.Context, s Session) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sessions[s.ID] = s
	m.sessByHash[s.TokenHash] = s.ID
	return nil
}

func (m *Memory) SessionByHash(_ context.Context, hash string) (Session, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	id, ok := m.sessByHash[hash]
	if !ok {
		return Session{}, ErrNotFound
	}
	return m.sessions[id], nil
}

func (m *Memory) DeleteSession(_ context.Context, id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.sessions[id]
	if !ok {
		return nil
	}
	delete(m.sessByHash, s.TokenHash)
	delete(m.sessions, id)
	return nil
}

func (m *Memory) CreateAPIKey(_ context.Context, k APIKey) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.keys[k.ID] = k
	m.keyByHash[k.KeyHash] = k.ID
	return nil
}

func (m *Memory) APIKeyByHash(_ context.Context, hash string) (APIKey, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	id, ok := m.keyByHash[hash]
	if !ok {
		return APIKey{}, ErrNotFound
	}
	return m.keys[id], nil
}

func (m *Memory) RevokeUserKeys(_ context.Context, userID string, at string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for id, k := range m.keys {
		if k.UserID == userID && k.RevokedAt == "" {
			k.RevokedAt = at
			m.keys[id] = k
		}
	}
	return nil
}

func (m *Memory) CreateInvite(_ context.Context, inv Invite) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.invites[inv.ID] = inv
	return nil
}

func (m *Memory) Invite(_ context.Context, id string) (Invite, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	inv, ok := m.invites[id]
	if !ok {
		return Invite{}, ErrNotFound
	}
	return inv, nil
}

func (m *Memory) ListInvites(_ context.Context, accountID string) ([]Invite, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Invite
	for _, inv := range m.invites {
		if inv.AccountID == accountID {
			out = append(out, inv)
		}
	}
	return out, nil
}

func (m *Memory) SaveInvite(_ context.Context, inv Invite) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.invites[inv.ID]; !ok {
		return ErrNotFound
	}
	m.invites[inv.ID] = inv
	return nil
}

func (m *Memory) SaveJob(_ context.Context, j Job) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.jobs[jobKey(j.AccountID, j.ID)] = j
	return nil
}

func (m *Memory) Job(_ context.Context, accountID, id string) (Job, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	j, ok := m.jobs[jobKey(accountID, id)]
	if !ok {
		return Job{}, ErrNotFound
	}
	return j, nil
}

func matchJob(j Job, f JobFilter) bool {
	if j.AccountID != f.AccountID {
		return false
	}
	if f.Status != "" && j.Status != f.Status {
		return false
	}
	if f.Stopped != nil && j.Stopped != *f.Stopped {
		return false
	}
	if f.ApplyKind != "" && j.ApplyKind != f.ApplyKind {
		return false
	}
	if f.Location != "" && !strings.Contains(strings.ToLower(j.Location), strings.ToLower(f.Location)) {
		return false
	}
	if f.Company != "" && !strings.Contains(strings.ToLower(j.Company), strings.ToLower(f.Company)) {
		return false
	}
	if f.Remote != "" && !strings.EqualFold(j.Remote, f.Remote) {
		return false
	}
	if f.HasPay != nil && *f.HasPay != (strings.TrimSpace(j.Pay) != "") {
		return false
	}
	if f.ScoreMin != nil && (j.Score == nil || *j.Score < *f.ScoreMin) {
		return false
	}
	if f.ScoreMax != nil && (j.Score == nil || *j.Score > *f.ScoreMax) {
		return false
	}
	if len(f.Lane) > 0 {
		ok := false
		for _, s := range f.Lane {
			if j.Status == s {
				ok = true
				break
			}
		}
		if !ok {
			return false
		}
	}
	if q := strings.ToLower(strings.TrimSpace(f.Q)); q != "" {
		blob := strings.ToLower(j.Company + " " + j.Title + " " + j.Location + " " + j.Notes)
		if !strings.Contains(blob, q) {
			return false
		}
	}
	return true
}

func (m *Memory) ListJobs(_ context.Context, f JobFilter) ([]Job, int, int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var matched []Job
	total := 0
	for _, j := range m.jobs {
		if j.AccountID == f.AccountID {
			total++
		}
		if matchJob(j, f) {
			matched = append(matched, j)
		}
	}
	start := f.Offset
	if start < 0 {
		start = 0
	}
	if start > len(matched) {
		start = len(matched)
	}
	end := len(matched)
	if f.Limit > 0 && start+f.Limit < end {
		end = start + f.Limit
	}
	return append([]Job(nil), matched[start:end]...), len(matched), total, nil
}

func (m *Memory) DeleteJob(_ context.Context, accountID, id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	key := jobKey(accountID, id)
	if _, ok := m.jobs[key]; !ok {
		return ErrNotFound
	}
	delete(m.jobs, key)
	return nil
}

func (m *Memory) FindDuplicate(_ context.Context, accountID, applyURL, company, title, location string) (Job, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	applyURL = strings.TrimSpace(applyURL)
	for _, j := range m.jobs {
		if j.AccountID != accountID {
			continue
		}
		if applyURL != "" && j.ApplyURL == applyURL {
			return j, true, nil
		}
		if strings.EqualFold(j.Company, company) && strings.EqualFold(j.Title, title) && strings.EqualFold(j.Location, location) {
			return j, true, nil
		}
	}
	return Job{}, false, nil
}

func (m *Memory) CountByStatus(_ context.Context, accountID string) (map[string]int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := map[string]int{}
	for _, j := range m.jobs {
		if j.AccountID == accountID {
			out[j.Status]++
		}
	}
	return out, nil
}

func (m *Memory) AddEvent(_ context.Context, e Event) (Event, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.eventSeq++
	e.ID = m.eventSeq
	m.events = append(m.events, e)
	return e, nil
}

func (m *Memory) ListEvents(_ context.Context, accountID, jobID string, limit int) ([]Event, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Event
	for i := len(m.events) - 1; i >= 0; i-- {
		e := m.events[i]
		if e.AccountID != accountID {
			continue
		}
		if jobID != "" && e.JobID != jobID {
			continue
		}
		out = append(out, e)
		if limit > 0 && len(out) >= limit {
			break
		}
	}
	return out, nil
}

func (m *Memory) SaveQueue(_ context.Context, q QueueItem) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.queue[q.AccountID+"\x00"+q.ID] = q
	return nil
}

func (m *Memory) QueueByID(_ context.Context, accountID, id string) (QueueItem, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	q, ok := m.queue[accountID+"\x00"+id]
	if !ok {
		return QueueItem{}, ErrNotFound
	}
	return q, nil
}

func (m *Memory) QueueByDedupe(_ context.Context, accountID, key string) (QueueItem, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, q := range m.queue {
		if q.AccountID == accountID && q.DedupeKey == key {
			return q, true, nil
		}
	}
	return QueueItem{}, false, nil
}

func (m *Memory) ClaimQueue(_ context.Context, accountID, who string, kinds []string, now, leaseUntil string) (QueueItem, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	allow := map[string]bool{}
	for _, k := range kinds {
		allow[k] = true
	}
	var pick *QueueItem
	for _, q := range m.queue {
		if q.AccountID != accountID || !allow[q.Kind] {
			continue
		}
		if q.Status != "open" && q.Status != "claimed" {
			continue
		}
		if q.Status == "claimed" && q.LeaseUntil != "" && q.LeaseUntil >= now && q.ClaimedBy == who {
			continue
		}
		if q.Status == "claimed" && q.LeaseUntil != "" && q.LeaseUntil >= now {
			continue
		}
		cp := q
		if pick == nil || cp.ID < pick.ID {
			pick = &cp
		}
	}
	if pick == nil {
		return QueueItem{}, false, nil
	}
	pick.Status = "claimed"
	pick.ClaimedBy = who
	pick.LeaseUntil = leaseUntil
	m.queue[pick.AccountID+"\x00"+pick.ID] = *pick
	return *pick, true, nil
}

func (m *Memory) ListQueue(_ context.Context, accountID, claimedBy, status string) ([]QueueItem, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []QueueItem
	for _, q := range m.queue {
		if q.AccountID != accountID {
			continue
		}
		if claimedBy != "" && q.ClaimedBy != claimedBy {
			continue
		}
		if status != "" && q.Status != status {
			continue
		}
		out = append(out, q)
	}
	return out, nil
}

func (m *Memory) SavePerson(_ context.Context, p Person) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.people[jobKey(p.AccountID, p.ID)] = p
	return nil
}

func (m *Memory) Person(_ context.Context, accountID, id string) (Person, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.people[jobKey(accountID, id)]
	if !ok {
		return Person{}, ErrNotFound
	}
	return p, nil
}

func (m *Memory) ListPeople(_ context.Context, accountID, company, jobID string) ([]Person, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Person
	for _, p := range m.people {
		if p.AccountID != accountID {
			continue
		}
		if company != "" && !strings.EqualFold(p.Company, company) {
			continue
		}
		if jobID != "" && p.JobID != jobID {
			continue
		}
		out = append(out, p)
	}
	return out, nil
}

func (m *Memory) SaveMemory(_ context.Context, item MemoryItem) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.memory[jobKey(item.AccountID, item.ID)] = item
	return nil
}

func (m *Memory) Memory(_ context.Context, accountID, id string) (MemoryItem, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	item, ok := m.memory[jobKey(accountID, id)]
	if !ok {
		return MemoryItem{}, ErrNotFound
	}
	return item, nil
}

func (m *Memory) ListMemory(_ context.Context, accountID, pod string) ([]MemoryItem, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []MemoryItem
	for _, item := range m.memory {
		if item.AccountID != accountID {
			continue
		}
		if pod != "" && item.Pod != pod && !strings.HasPrefix(item.Pod, pod) {
			continue
		}
		out = append(out, item)
	}
	return out, nil
}

func (m *Memory) DeleteMemory(_ context.Context, accountID, id string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	key := jobKey(accountID, id)
	if _, ok := m.memory[key]; !ok {
		return ErrNotFound
	}
	delete(m.memory, key)
	return nil
}

func (m *Memory) SaveMessage(_ context.Context, msg Message) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.messages[msg.ID] = msg
	return nil
}

func (m *Memory) ListMessages(_ context.Context, accountID string, unreadOnly bool) ([]Message, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Message
	for _, msg := range m.messages {
		if msg.AccountID != accountID {
			continue
		}
		if unreadOnly && msg.ReadAt != "" {
			continue
		}
		out = append(out, msg)
	}
	return out, nil
}

func (m *Memory) Message(_ context.Context, accountID, id string) (Message, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	msg, ok := m.messages[id]
	if !ok || msg.AccountID != accountID {
		return Message{}, ErrNotFound
	}
	return msg, nil
}

func (m *Memory) SaveSkill(_ context.Context, s Skill) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.skills[s.ID] = s
	return nil
}

func (m *Memory) Skill(_ context.Context, id string) (Skill, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.skills[id]
	if !ok {
		return Skill{}, ErrNotFound
	}
	return s, nil
}

func (m *Memory) ListSkills(_ context.Context, accountID, scope, status, tag string) ([]Skill, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Skill
	for _, s := range m.skills {
		if s.Scope == "shared" {
			if accountID != "" && s.AccountID != "" && s.AccountID != accountID && s.AccountID != "shared" {
				continue
			}
		} else if s.AccountID != accountID {
			continue
		}
		if scope != "" && s.Scope != scope {
			continue
		}
		if status != "" && s.Status != status {
			continue
		}
		if tag != "" && !strings.Contains(string(s.Tags), `"`+tag+`"`) {
			continue
		}
		out = append(out, s)
	}
	return out, nil
}

func (m *Memory) SaveMCP(_ context.Context, item MCP) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.mcps[item.AccountID+"\x00"+item.ID] = item
	return nil
}

func (m *Memory) MCP(_ context.Context, accountID, idOrSlug string) (MCP, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, item := range m.mcps {
		if item.AccountID != accountID && item.AccountID != "shared" {
			continue
		}
		if item.ID == idOrSlug || item.Slug == idOrSlug {
			return item, nil
		}
	}
	return MCP{}, ErrNotFound
}

func (m *Memory) ListMCPs(_ context.Context, accountID string) ([]MCP, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []MCP
	for _, item := range m.mcps {
		if item.AccountID == accountID || item.AccountID == "shared" {
			out = append(out, item)
		}
	}
	return out, nil
}

func (m *Memory) SaveRecording(_ context.Context, r Recording) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.records[r.ID] = r
	return nil
}

func (m *Memory) Recording(_ context.Context, id string) (Recording, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	r, ok := m.records[id]
	if !ok {
		return Recording{}, ErrNotFound
	}
	return r, nil
}

func (m *Memory) ListRecordings(_ context.Context, accountID, status string) ([]Recording, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Recording
	for _, r := range m.records {
		if r.AccountID != accountID {
			continue
		}
		if status != "" && r.Status != status {
			continue
		}
		out = append(out, r)
	}
	return out, nil
}

func (m *Memory) SavePresence(_ context.Context, p Presence) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.presence[p.AccountID+"\x00"+p.UserID] = p
	return nil
}

func (m *Memory) ListPresence(_ context.Context, accountID string) ([]Presence, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Presence
	for _, p := range m.presence {
		if p.AccountID == accountID {
			out = append(out, p)
		}
	}
	return out, nil
}

func (m *Memory) AddBurn(_ context.Context, b Burn) (Burn, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.burnSeq++
	b.ID = m.burnSeq
	m.burns = append(m.burns, b)
	return b, nil
}

func (m *Memory) ListBurns(_ context.Context, accountID string, limit int) ([]Burn, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Burn
	for i := len(m.burns) - 1; i >= 0; i-- {
		if m.burns[i].AccountID != accountID {
			continue
		}
		out = append(out, m.burns[i])
		if limit > 0 && len(out) >= limit {
			break
		}
	}
	return out, nil
}

func (m *Memory) SavePeer(_ context.Context, p Peer) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.peers[p.ID] = p
	return nil
}

func (m *Memory) ListPeers(_ context.Context, accountID string) ([]Peer, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []Peer
	for _, p := range m.peers {
		if p.AccountID == accountID {
			out = append(out, p)
		}
	}
	return out, nil
}

func (m *Memory) SaveTask(_ context.Context, t Task) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.tasks = append(m.tasks, t)
	return nil
}

func (m *Memory) PutKV(_ context.Context, key, value, _ string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.kv[key] = value
	return nil
}

func (m *Memory) GetKV(_ context.Context, key string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	v, ok := m.kv[key]
	if !ok {
		return "", ErrNotFound
	}
	return v, nil
}
