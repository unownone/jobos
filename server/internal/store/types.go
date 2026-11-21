package store

import (
	"context"
	"encoding/json"
	"errors"
)

var (
	ErrNotFound = errors.New("not found")
	ErrConflict = errors.New("conflict")
)

type Account struct {
	ID           string `json:"id"`
	Username     string `json:"username"`
	PasswordHash string `json:"-"`
	CreatedAt    string `json:"created_at"`
}

type User struct {
	ID           string          `json:"id"`
	AccountID    string          `json:"account_id"`
	Kind         string          `json:"kind"`
	Track        string          `json:"track,omitempty"`
	Email        string          `json:"email,omitempty"`
	PasswordHash string          `json:"-"`
	DisplayName  string          `json:"display_name"`
	Metadata     json.RawMessage `json:"metadata,omitempty"`
	CreatedBy    string          `json:"created_by,omitempty"`
	DisabledAt   string          `json:"disabled_at,omitempty"`
	CreatedAt    string          `json:"created_at"`
}

type Session struct {
	ID        string `json:"id"`
	AccountID string `json:"account_id"`
	UserID    string `json:"user_id"`
	TokenHash string `json:"-"`
	CSRFHash  string `json:"-"`
	ExpiresAt string `json:"expires_at"`
	LastSeen  string `json:"last_seen"`
}

type APIKey struct {
	ID        string `json:"id"`
	AccountID string `json:"account_id"`
	UserID    string `json:"user_id"`
	Prefix    string `json:"prefix"`
	KeyHash   string `json:"-"`
	CreatedAt string `json:"created_at"`
	RevokedAt string `json:"revoked_at,omitempty"`
}

type Invite struct {
	ID                  string `json:"id"`
	AccountID           string `json:"account_id"`
	Track               string `json:"track"`
	Mode                string `json:"mode"`
	SecretHash          string `json:"-"`
	MaxRedemptions      int    `json:"max_redemptions"`
	Redemptions         int    `json:"redemptions"`
	ExpiresAt           string `json:"expires_at"`
	RevokedAt           string `json:"revoked_at,omitempty"`
	CreatedBy           string `json:"created_by"`
	AllowMultipleOwners bool   `json:"allow_multiple_owners"`
	CreatedAt           string `json:"created_at"`
}

type Job struct {
	AccountID      string          `json:"account_id"`
	ID             string          `json:"id"`
	Company        string          `json:"company"`
	Title          string          `json:"title"`
	Location       string          `json:"location,omitempty"`
	Remote         string          `json:"remote,omitempty"`
	URL            string          `json:"url,omitempty"`
	ApplyURL       string          `json:"apply_url,omitempty"`
	ApplyKind      string          `json:"apply_kind,omitempty"`
	ATS            string          `json:"ats,omitempty"`
	ReqID          string          `json:"req_id,omitempty"`
	Sources        json.RawMessage `json:"sources,omitempty"`
	Status         string          `json:"status"`
	Score          *float64        `json:"score,omitempty"`
	Owners         json.RawMessage `json:"owners,omitempty"`
	ApplyPacket    json.RawMessage `json:"apply_packet,omitempty"`
	OutreachPacket json.RawMessage `json:"outreach_packet,omitempty"`
	Research       json.RawMessage `json:"research,omitempty"`
	Proof          json.RawMessage `json:"proof,omitempty"`
	Notes          string          `json:"notes,omitempty"`
	Description    string          `json:"description,omitempty"`
	Expectations   string          `json:"expectations,omitempty"`
	Pay            string          `json:"pay,omitempty"`
	PostedAt       string          `json:"posted_at,omitempty"`
	Rejection      json.RawMessage `json:"rejection,omitempty"`
	Conflicts      json.RawMessage `json:"conflicts,omitempty"`
	Stopped        bool            `json:"stopped"`
	StopReason     string          `json:"stop_reason,omitempty"`
	CreatedAt      string          `json:"created_at"`
	UpdatedAt      string          `json:"updated_at"`
	CreatedByRole  string          `json:"created_by_role,omitempty"`
	Claim          *QueueItem      `json:"claim,omitempty"`
}

type JobFilter struct {
	AccountID string
	Status    string
	Q         string
	Stopped   *bool
	ScoreMin  *float64
	ScoreMax  *float64
	Location  string
	ApplyKind string
	Remote    string
	HasPay    *bool
	Company   string
	Lane      []string
	Limit     int
	Offset    int
}

type Event struct {
	ID         int64           `json:"id"`
	AccountID  string          `json:"account_id"`
	TS         string          `json:"ts"`
	JobID      string          `json:"job_id,omitempty"`
	ActorRole  string          `json:"actor_role"`
	Actor      string          `json:"actor,omitempty"`
	Action     string          `json:"action"`
	FromStatus string          `json:"from_status,omitempty"`
	ToStatus   string          `json:"to_status,omitempty"`
	Note       string          `json:"note,omitempty"`
	Fields     json.RawMessage `json:"fields,omitempty"`
}

type QueueItem struct {
	ID         string          `json:"id"`
	AccountID  string          `json:"account_id"`
	Kind       string          `json:"kind"`
	Track      string          `json:"track,omitempty"`
	JobID      string          `json:"job_id,omitempty"`
	Payload    json.RawMessage `json:"payload,omitempty"`
	Status     string          `json:"status"`
	ClaimedBy  string          `json:"claimed_by,omitempty"`
	LeaseUntil string          `json:"lease_until,omitempty"`
	Attempts   int             `json:"attempts"`
	DedupeKey  string          `json:"dedupe_key"`
	CreatedAt  string          `json:"created_at"`
}

type Person struct {
	AccountID       string          `json:"account_id"`
	ID              string          `json:"id"`
	Name            string          `json:"name"`
	Title           string          `json:"title,omitempty"`
	Company         string          `json:"company,omitempty"`
	JobID           string          `json:"job_id,omitempty"`
	LinkedinURL     string          `json:"linkedin_url,omitempty"`
	Email           string          `json:"email,omitempty"`
	EmailConfidence string          `json:"email_confidence,omitempty"`
	DoNotContact    bool            `json:"do_not_contact"`
	Touches         json.RawMessage `json:"touches,omitempty"`
	Notes           string          `json:"notes,omitempty"`
	CreatedAt       string          `json:"created_at"`
	UpdatedAt       string          `json:"updated_at"`
}

type MemoryItem struct {
	ID             string          `json:"id"`
	AccountID      string          `json:"account_id"`
	Pod            string          `json:"pod"`
	Kind           string          `json:"kind"`
	Title          string          `json:"title,omitempty"`
	Body           string          `json:"body"`
	JobID          string          `json:"job_id,omitempty"`
	Company        string          `json:"company,omitempty"`
	ContentHash    string          `json:"content_hash"`
	Importance     string          `json:"importance,omitempty"`
	ExpiresAt      string          `json:"expires_at,omitempty"`
	Pinned         bool            `json:"pinned"`
	Tags           json.RawMessage `json:"tags,omitempty"`
	SolidifyStatus string          `json:"solidify_status"`
	CreatedBy      string          `json:"created_by,omitempty"`
	CreatedAt      string          `json:"created_at"`
	UpdatedAt      string          `json:"updated_at"`
}

type Message struct {
	ID         string `json:"id"`
	AccountID  string `json:"account_id"`
	FromUserID string `json:"from_user_id"`
	ToUserID   string `json:"to_user_id,omitempty"`
	ToTrack    string `json:"to_track,omitempty"`
	JobID      string `json:"job_id,omitempty"`
	Type       string `json:"type"`
	Body       string `json:"body"`
	CreatedAt  string `json:"created_at"`
	ReadAt     string `json:"read_at,omitempty"`
}

type Skill struct {
	ID        string          `json:"id"`
	AccountID string          `json:"account_id"`
	Slug      string          `json:"slug"`
	Name      string          `json:"name"`
	Kind      string          `json:"kind"`
	Role      string          `json:"role"`
	Tags      json.RawMessage `json:"tags"`
	Scope     string          `json:"scope"`
	OwnerID   string          `json:"owner_user_id,omitempty"`
	Status    string          `json:"status"`
	Platform  string          `json:"platform,omitempty"`
	Body      string          `json:"body"`
	Origin    string          `json:"origin"`
	Version   int             `json:"version"`
	CreatedAt string          `json:"created_at"`
	UpdatedAt string          `json:"updated_at"`
}

type MCP struct {
	AccountID  string          `json:"account_id"`
	ID         string          `json:"id"`
	Slug       string          `json:"slug"`
	Name       string          `json:"name"`
	Kind       string          `json:"kind"`
	Status     string          `json:"status"`
	Capability json.RawMessage `json:"capability"`
	Roles      json.RawMessage `json:"roles"`
	Platforms  json.RawMessage `json:"platforms"`
	Source     string          `json:"source,omitempty"`
	Install    string          `json:"install,omitempty"`
	Auth       string          `json:"auth,omitempty"`
	Notes      string          `json:"notes,omitempty"`
	Origin     string          `json:"origin"`
	CreatedAt  string          `json:"created_at"`
	UpdatedAt  string          `json:"updated_at"`
}

type Recording struct {
	ID          string `json:"id"`
	AccountID   string `json:"account_id"`
	SkillID     string `json:"skill_id"`
	SubmitterID string `json:"submitter_user_id"`
	Origin      string `json:"origin"`
	Body        string `json:"body"`
	Status      string `json:"status"`
	Note        string `json:"proctor_note,omitempty"`
	CreatedAt   string `json:"created_at"`
}

type Presence struct {
	AccountID string `json:"account_id"`
	UserID    string `json:"user_id"`
	Status    string `json:"status"`
	TaskID    string `json:"task_id,omitempty"`
	LastBeat  string `json:"last_heartbeat"`
	UserAgent string `json:"user_agent,omitempty"`
}

type Burn struct {
	ID               int64   `json:"id"`
	AccountID        string  `json:"account_id"`
	TS               string  `json:"ts"`
	ToolName         string  `json:"tool_name"`
	Skill            string  `json:"skill,omitempty"`
	Lane             string  `json:"lane,omitempty"`
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	TotalTokens      int     `json:"total_tokens"`
	CostUSD          float64 `json:"cost_usd"`
	JobID            string  `json:"job_id,omitempty"`
	ActorRole        string  `json:"actor_role,omitempty"`
	Actor            string  `json:"actor,omitempty"`
}

type Peer struct {
	ID        string `json:"id"`
	AccountID string `json:"account_id"`
	Name      string `json:"name"`
	URL       string `json:"url"`
	CreatedAt string `json:"created_at"`
}

type Task struct {
	ID        string          `json:"id"`
	AccountID string          `json:"account_id"`
	Track     string          `json:"track,omitempty"`
	State     string          `json:"state"`
	Payload   json.RawMessage `json:"payload"`
	CreatedAt string          `json:"created_at"`
}

type Store interface {
	Name() string
	Ping(ctx context.Context) error
	Close() error

	CreateAccount(ctx context.Context, a Account, admin User) error
	AccountByUsername(ctx context.Context, username string) (Account, User, error)

	CreateUser(ctx context.Context, u User) error
	User(ctx context.Context, id string) (User, error)
	ListUsers(ctx context.Context, accountID, kind, track string) ([]User, error)
	FirstAdmin(ctx context.Context) (User, error)
	SaveUser(ctx context.Context, u User) error

	CreateSession(ctx context.Context, s Session) error
	SessionByHash(ctx context.Context, hash string) (Session, error)
	DeleteSession(ctx context.Context, id string) error

	CreateAPIKey(ctx context.Context, k APIKey) error
	APIKeyByHash(ctx context.Context, hash string) (APIKey, error)
	RevokeUserKeys(ctx context.Context, userID string, at string) error

	CreateInvite(ctx context.Context, inv Invite) error
	Invite(ctx context.Context, id string) (Invite, error)
	ListInvites(ctx context.Context, accountID string) ([]Invite, error)
	SaveInvite(ctx context.Context, inv Invite) error

	SaveJob(ctx context.Context, j Job) error
	Job(ctx context.Context, accountID, id string) (Job, error)
	ListJobs(ctx context.Context, f JobFilter) ([]Job, int, int, error)
	DeleteJob(ctx context.Context, accountID, id string) error
	FindDuplicate(ctx context.Context, accountID, applyURL, company, title, location string) (Job, bool, error)
	CountByStatus(ctx context.Context, accountID string) (map[string]int, error)

	AddEvent(ctx context.Context, e Event) (Event, error)
	ListEvents(ctx context.Context, accountID, jobID string, limit int) ([]Event, error)

	SaveQueue(ctx context.Context, q QueueItem) error
	QueueByID(ctx context.Context, accountID, id string) (QueueItem, error)
	QueueByDedupe(ctx context.Context, accountID, key string) (QueueItem, bool, error)
	ClaimQueue(ctx context.Context, accountID, who string, kinds []string, now, leaseUntil string) (QueueItem, bool, error)
	ListQueue(ctx context.Context, accountID, claimedBy, status string) ([]QueueItem, error)

	SavePerson(ctx context.Context, p Person) error
	Person(ctx context.Context, accountID, id string) (Person, error)
	ListPeople(ctx context.Context, accountID, company, jobID string) ([]Person, error)

	SaveMemory(ctx context.Context, m MemoryItem) error
	Memory(ctx context.Context, accountID, id string) (MemoryItem, error)
	ListMemory(ctx context.Context, accountID, pod string) ([]MemoryItem, error)
	DeleteMemory(ctx context.Context, accountID, id string) error

	SaveMessage(ctx context.Context, m Message) error
	ListMessages(ctx context.Context, accountID string, unreadOnly bool) ([]Message, error)
	Message(ctx context.Context, accountID, id string) (Message, error)

	SaveSkill(ctx context.Context, s Skill) error
	Skill(ctx context.Context, id string) (Skill, error)
	ListSkills(ctx context.Context, accountID, scope, status, tag string) ([]Skill, error)

	SaveMCP(ctx context.Context, item MCP) error
	MCP(ctx context.Context, accountID, idOrSlug string) (MCP, error)
	ListMCPs(ctx context.Context, accountID string) ([]MCP, error)

	SaveRecording(ctx context.Context, r Recording) error
	Recording(ctx context.Context, id string) (Recording, error)
	ListRecordings(ctx context.Context, accountID, status string) ([]Recording, error)

	SavePresence(ctx context.Context, p Presence) error
	ListPresence(ctx context.Context, accountID string) ([]Presence, error)

	AddBurn(ctx context.Context, b Burn) (Burn, error)
	ListBurns(ctx context.Context, accountID string, limit int) ([]Burn, error)

	SavePeer(ctx context.Context, p Peer) error
	ListPeers(ctx context.Context, accountID string) ([]Peer, error)
	SaveTask(ctx context.Context, t Task) error
	Task(ctx context.Context, accountID, id string) (Task, error)
	ListTasks(ctx context.Context, accountID string, limit int) ([]Task, error)

	PutKV(ctx context.Context, key, value, at string) error
	GetKV(ctx context.Context, key string) (string, error)
}
