package agentflow

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"time"
)

const (
	accessPrefix  = "jhmcp_at_"
	refreshPrefix = "jhmcp_rt_"
	clientPrefix  = "jhmcp_cid_"
	codePrefix    = "jhmcp_cd_"
	scope         = "jobos"
)

var ErrInvalidGrant = errors.New("invalid_grant")

type Client struct {
	ID          string
	Name        string
	Redirects   []string
	AuthMethod  string
	SecretHash  string
	CreatedAt   string
}

type codeRow struct {
	Hash       string
	ClientID   string
	AccountID  string
	UserID     string
	Redirect   string
	Challenge  string
	Scope      string
	ExpiresAt  string
	UsedAt     string
}

type Grant struct {
	ID                   string
	AccountID            string
	UserID               string
	ClientID             string
	ClientName           string
	Scope                string
	AccessHash           string
	RefreshHash          string
	PreviousRefreshHash  string
	AccessExpiresAt      string
	RefreshExpiresAt     string
	SessionID            string
	RevokedAt            string
	LastUsedAt           string
}

type AgentSession struct {
	ID           string
	AccountID    string
	GrantID      string
	Label        string
	Lanes        []string
	Capabilities Capabilities
	Status       string
}

type Steer struct {
	ID        string `json:"id"`
	Body      string `json:"body"`
	SessionID string `json:"session_id,omitempty"`
	CreatedAt string `json:"created_at"`
}

type Use struct {
	ID        string `json:"id"`
	Kind      string `json:"kind"`
	Name      string `json:"name"`
	SessionID string `json:"session_id"`
	CreatedAt string `json:"created_at"`
}

type Loop struct {
	ID        string `json:"id"`
	Lane      string `json:"lane"`
	SessionID string `json:"session_id"`
	Status    string `json:"status"`
}

type Flow struct {
	mu       sync.Mutex
	clients  map[string]Client
	codes    map[string]codeRow
	grants   map[string]Grant
	sessions map[string]AgentSession
	steers   []Steer
	uses     []Use
	loops    []Loop
	spent    map[string]map[string]bool
}

func New() *Flow {
	return &Flow{
		clients: map[string]Client{}, codes: map[string]codeRow{}, grants: map[string]Grant{},
		sessions: map[string]AgentSession{}, spent: map[string]map[string]bool{},
	}
}

func (f *Flow) RegisterClient(name, method string, redirects []string) (map[string]any, error) {
	method = strings.TrimSpace(method)
	if method == "" {
		method = "none"
	}
	if method != "none" && method != "client_secret_post" {
		return nil, errors.New("token_endpoint_auth_method must be none or client_secret_post")
	}
	name = strings.TrimSpace(name)
	if name == "" {
		name = "AI client"
	}
	if len(name) > 120 {
		name = name[:120]
	}
	var uris []string
	for _, uri := range redirects {
		text := strings.TrimSpace(uri)
		if !RedirectURIAllowed(text) {
			return nil, errors.New("redirect_uri is not allowed: " + text)
		}
		if !contains(uris, text) {
			uris = append(uris, text)
		}
	}
	if len(uris) == 0 {
		return nil, errors.New("redirect_uris is required")
	}
	id := clientPrefix + token(24)
	secret := ""
	hash := ""
	if method == "client_secret_post" {
		secret = "jhmcp_cs_" + token(32)
		hash = sha(secret)
	}
	f.mu.Lock()
	f.clients[id] = Client{ID: id, Name: name, Redirects: uris, AuthMethod: method, SecretHash: hash, CreatedAt: now()}
	f.mu.Unlock()
	out := map[string]any{
		"client_id": id, "client_name": name, "redirect_uris": uris,
		"token_endpoint_auth_method": method,
		"grant_types":                []string{"authorization_code", "refresh_token"},
		"response_types":             []string{"code"},
		"scope":                      scope,
	}
	if secret != "" {
		out["client_secret"] = secret
	}
	return out, nil
}

func (f *Flow) Client(id string) (Client, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	c, ok := f.clients[id]
	return c, ok
}

func (f *Flow) SecretOK(client Client, secret string) bool {
	if client.AuthMethod == "none" {
		return true
	}
	if secret == "" || client.SecretHash == "" {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(sha(secret)), []byte(client.SecretHash)) == 1
}

func (f *Flow) IssueCode(clientID, accountID, userID, redirectURI, challenge string) string {
	code := codePrefix + token(32)
	f.mu.Lock()
	f.codes[sha(code)] = codeRow{
		Hash: sha(code), ClientID: clientID, AccountID: accountID, UserID: userID,
		Redirect: redirectURI, Challenge: challenge, Scope: scope,
		ExpiresAt: time.Now().UTC().Add(10 * time.Minute).Format(time.RFC3339),
	}
	f.mu.Unlock()
	return code
}

func (f *Flow) ExchangeCode(code, clientID, redirectURI, verifier string) (map[string]any, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	row, ok := f.codes[sha(code)]
	if !ok || row.UsedAt != "" || row.ClientID != clientID || row.Redirect != redirectURI || row.ExpiresAt < now() {
		return nil, ErrInvalidGrant
	}
	if !PKCEVerifierOK(verifier) || PKCSES256(verifier) != row.Challenge {
		return nil, ErrInvalidGrant
	}
	row.UsedAt = now()
	f.codes[row.Hash] = row
	client := f.clients[clientID]
	name := client.Name
	if name == "" {
		name = "AI client"
	}
	return f.mintLocked(row.AccountID, row.UserID, clientID, name, row.Scope, "", ""), nil
}

func (f *Flow) Refresh(refreshToken, clientID string) (map[string]any, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	digest := sha(refreshToken)
	var grant Grant
	found := false
	for _, row := range f.grants {
		if row.ClientID != clientID || row.RevokedAt != "" {
			continue
		}
		if row.RefreshHash == digest || row.PreviousRefreshHash == digest || f.spent[row.ID][digest] {
			grant = row
			found = true
			break
		}
	}
	if !found || grant.RefreshExpiresAt < now() {
		return nil, ErrInvalidGrant
	}
	if subtle.ConstantTimeCompare([]byte(digest), []byte(grant.RefreshHash)) != 1 {
		grant.RevokedAt = now()
		f.grants[grant.ID] = grant
		return nil, ErrInvalidGrant
	}
	return f.mintLocked(grant.AccountID, grant.UserID, grant.ClientID, grant.ClientName, grant.Scope, grant.SessionID, grant.ID), nil
}

func (f *Flow) mintLocked(accountID, userID, clientID, clientName, scopeValue, sessionID, replaceID string) map[string]any {
	access := accessPrefix + token(32)
	refresh := refreshPrefix + token(32)
	id := replaceID
	if id == "" {
		id = "mgr_" + token(8)
	}
	prev := ""
	if replaceID != "" {
		prev = f.grants[replaceID].RefreshHash
		if f.spent[id] == nil {
			f.spent[id] = map[string]bool{}
		}
		f.spent[id][prev] = true
	}
	f.grants[id] = Grant{
		ID: id, AccountID: accountID, UserID: userID, ClientID: clientID, ClientName: clientName, Scope: scopeValue,
		AccessHash: sha(access), RefreshHash: sha(refresh), PreviousRefreshHash: prev,
		AccessExpiresAt: time.Now().UTC().Add(24 * time.Hour).Format(time.RFC3339),
		RefreshExpiresAt: time.Now().UTC().Add(90 * 24 * time.Hour).Format(time.RFC3339),
		SessionID: sessionID, LastUsedAt: now(),
	}
	return map[string]any{
		"access_token": access, "token_type": "Bearer", "expires_in": 86400,
		"refresh_token": refresh, "scope": scopeValue, "grant_id": id,
	}
}

// EnsureHubKeyGrant binds a long-lived Hub API key (jh_agt_… / jh_own_…) to an MCP grant.
// Access lasts 90 days; clients keep the Bearer key in MCP config (no OAuth refresh needed).
func (f *Flow) EnsureHubKeyGrant(accountID, userID, clientName, apiKey string) Grant {
	f.mu.Lock()
	defer f.mu.Unlock()
	digest := sha(apiKey)
	for id, grant := range f.grants {
		if grant.AccessHash != digest {
			continue
		}
		if grant.RevokedAt != "" {
			continue
		}
		if grant.AccessExpiresAt < now() {
			grant.AccessExpiresAt = time.Now().UTC().Add(90 * 24 * time.Hour).Format(time.RFC3339)
		}
		grant.AccountID = accountID
		grant.UserID = userID
		if clientName != "" {
			grant.ClientName = clientName
		}
		grant.LastUsedAt = now()
		f.grants[id] = grant
		return grant
	}
	id := "mgr_key_" + token(8)
	if clientName == "" {
		clientName = "Hub API key"
	}
	grant := Grant{
		ID: id, AccountID: accountID, UserID: userID, ClientID: "hub_key", ClientName: clientName, Scope: scope,
		AccessHash: digest, AccessExpiresAt: time.Now().UTC().Add(90 * 24 * time.Hour).Format(time.RFC3339),
		RefreshExpiresAt: time.Now().UTC().Add(90 * 24 * time.Hour).Format(time.RFC3339),
		LastUsedAt: now(),
	}
	f.grants[id] = grant
	return grant
}

func (f *Flow) GrantForAccess(token string) (Grant, string) {
	if token == "" {
		return Grant{}, "invalid_token"
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	digest := sha(token)
	for id, grant := range f.grants {
		if grant.AccessHash != digest {
			continue
		}
		if grant.RevokedAt != "" || grant.AccessExpiresAt < now() {
			return Grant{}, "invalid_token"
		}
		grant.LastUsedAt = now()
		f.grants[id] = grant
		return grant, ""
	}
	return Grant{}, "invalid_token"
}

func (f *Flow) EnsureSession(grant Grant) AgentSession {
	f.mu.Lock()
	defer f.mu.Unlock()
	current := f.grants[grant.ID]
	if current.SessionID != "" {
		if session, ok := f.sessions[current.SessionID]; ok && session.Status == "active" {
			return session
		}
	}
	session := AgentSession{
		ID: "ags_" + token(8), AccountID: current.AccountID, GrantID: current.ID,
		Label: current.ClientName, Status: "active", Capabilities: Capabilities{},
	}
	f.sessions[session.ID] = session
	current.SessionID = session.ID
	f.grants[current.ID] = current
	return session
}

func (f *Flow) EndSession(accountID, sessionID string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	session, ok := f.sessions[sessionID]
	if !ok || session.AccountID != accountID {
		return
	}
	session.Status = "ended"
	f.sessions[sessionID] = session
	for id, grant := range f.grants {
		if grant.SessionID == sessionID {
			grant.SessionID = ""
			f.grants[id] = grant
		}
	}
}

func (f *Flow) SetLabel(sessionID, label string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	session := f.sessions[sessionID]
	if len(label) > 120 {
		label = label[:120]
	}
	session.Label = label
	f.sessions[sessionID] = session
}

func (f *Flow) UpdateSession(session AgentSession) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.sessions[session.ID] = session
}

func (f *Flow) Session(id string) (AgentSession, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	session, ok := f.sessions[id]
	return session, ok
}

func (f *Flow) AddSteer(accountID, userID, body, sessionID string) (Steer, error) {
	body = strings.TrimSpace(body)
	if len(body) < 8 {
		return Steer{}, errors.New("steer is too short")
	}
	steer := Steer{ID: "str_" + token(6), Body: body, SessionID: sessionID, CreatedAt: now()}
	f.mu.Lock()
	f.steers = append(f.steers, steer)
	f.mu.Unlock()
	_ = accountID
	_ = userID
	return steer, nil
}

func (f *Flow) Steers(accountID string) []Steer {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.steers == nil {
		return []Steer{}
	}
	_ = accountID
	out := append([]Steer(nil), f.steers...)
	return out
}

func (f *Flow) RecordUse(sessionID, kind, name string) Use {
	use := Use{ID: "use_" + token(6), Kind: kind, Name: name, SessionID: sessionID, CreatedAt: now()}
	f.mu.Lock()
	f.uses = append(f.uses, use)
	f.mu.Unlock()
	return use
}

func (f *Flow) Uses() []Use {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.uses == nil {
		return []Use{}
	}
	return append([]Use(nil), f.uses...)
}

func (f *Flow) StartLoop(sessionID, lane string) Loop {
	loop := Loop{ID: "loop_" + token(6), Lane: lane, SessionID: sessionID, Status: "running"}
	f.mu.Lock()
	f.loops = append(f.loops, loop)
	f.mu.Unlock()
	return loop
}

func (f *Flow) Loops(sessionID string) []Loop {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []Loop
	for _, loop := range f.loops {
		if loop.SessionID == sessionID {
			out = append(out, loop)
		}
	}
	if out == nil {
		out = []Loop{}
	}
	return out
}

func (f *Flow) SetLoopStatus(id, status string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for i := range f.loops {
		if f.loops[i].ID == id {
			f.loops[i].Status = status
		}
	}
}

func (f *Flow) PublicGrants(accountID string) []map[string]any {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []map[string]any
	for _, grant := range f.grants {
		if grant.AccountID != accountID || grant.RevokedAt != "" {
			continue
		}
		item := map[string]any{"id": grant.ID, "client_name": grant.ClientName, "scope": grant.Scope}
		if grant.SessionID != "" {
			if session, ok := f.sessions[grant.SessionID]; ok {
				item["session"] = map[string]any{"id": session.ID, "label": session.Label, "lanes": session.Lanes, "status": session.Status}
			}
		}
		out = append(out, item)
	}
	if out == nil {
		out = []map[string]any{}
	}
	return out
}

func (f *Flow) Revoke(accountID, grantID string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	grant, ok := f.grants[grantID]
	if !ok || grant.AccountID != accountID {
		return false
	}
	grant.RevokedAt = now()
	f.grants[grantID] = grant
	return true
}

func (f *Flow) MarshalSession(session AgentSession) []byte {
	body, _ := json.Marshal(session)
	return body
}

func token(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func sha(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func now() string { return time.Now().UTC().Format(time.RFC3339) }
