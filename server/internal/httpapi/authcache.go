package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/store"
)

const (
	authCacheTTL   = 2 * time.Minute
	recallCacheTTL = 10 * time.Second
	candidateTTL   = 60 * time.Second
)

type cachedKey struct {
	Gen  string     `json:"gen"`
	User store.User `json:"user"`
}

type cachedSession struct {
	ID        string     `json:"id"`
	AccountID string     `json:"account_id"`
	UserID    string     `json:"user_id"`
	CSRFHash  string     `json:"csrf_hash"`
	ExpiresAt string     `json:"expires_at"`
	Gen       string     `json:"gen"`
	User      store.User `json:"user"`
}

func (s *Server) userGen(ctx context.Context, userID string) string {
	raw, ok, err := s.Cache.Get(ctx, "auth:gen:"+userID)
	if err != nil || !ok || len(raw) == 0 {
		return "0"
	}
	return string(raw)
}

func (s *Server) bumpUser(ctx context.Context, userID string) {
	_ = s.Cache.Set(ctx, "auth:gen:"+userID, []byte(now()), 0)
}

func (s *Server) cachedPrincipal(c *gin.Context, bearer string) (principal, bool) {
	raw, ok, err := s.Cache.Get(c.Request.Context(), "auth:key:"+hash(bearer))
	if err != nil || !ok {
		return principal{}, false
	}
	var hit cachedKey
	if json.Unmarshal(raw, &hit) != nil || hit.User.ID == "" || hit.User.DisabledAt != "" {
		return principal{}, false
	}
	if hit.Gen != s.userGen(c.Request.Context(), hit.User.ID) {
		return principal{}, false
	}
	return principalFromUser(hit.User, authKind(hit.User.Kind), c.GetHeader("X-Actor")), true
}

func (s *Server) storeKey(c *gin.Context, bearer string, user store.User) {
	if user.DisabledAt != "" {
		return
	}
	body, err := json.Marshal(cachedKey{Gen: s.userGen(c.Request.Context(), user.ID), User: user})
	if err != nil {
		return
	}
	_ = s.Cache.Set(c.Request.Context(), "auth:key:"+hash(bearer), body, authCacheTTL)
}

func (s *Server) cachedSession(c *gin.Context, raw string) (principal, bool) {
	blob, ok, err := s.Cache.Get(c.Request.Context(), "auth:sess:"+hash(raw))
	if err != nil || !ok {
		return principal{}, false
	}
	var hit cachedSession
	if json.Unmarshal(blob, &hit) != nil || hit.User.ID == "" || hit.User.DisabledAt != "" || hit.ExpiresAt < now() {
		return principal{}, false
	}
	if hit.Gen != s.userGen(c.Request.Context(), hit.User.ID) {
		return principal{}, false
	}
	if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead {
		csrfCookie, _ := c.Cookie(cookieCSRF)
		header := c.GetHeader("X-CSRF")
		if csrfCookie == "" || header == "" || !constEq(csrfCookie, header) || hit.CSRFHash != hash(header) {
			return principal{}, false
		}
	}
	p := principalFromUser(hit.User, "session", "")
	p.SessionID = hit.ID
	return p, true
}

func (s *Server) storeSession(c *gin.Context, raw string, sess store.Session, user store.User) {
	if user.DisabledAt != "" {
		return
	}
	body, err := json.Marshal(cachedSession{
		ID: sess.ID, AccountID: sess.AccountID, UserID: sess.UserID, CSRFHash: sess.CSRFHash,
		ExpiresAt: sess.ExpiresAt, Gen: s.userGen(c.Request.Context(), user.ID), User: user,
	})
	if err != nil {
		return
	}
	_ = s.Cache.Set(c.Request.Context(), "auth:sess:"+hash(raw), body, authCacheTTL)
}

func (s *Server) dropSession(c *gin.Context, raw string) {
	if raw == "" {
		return
	}
	_ = s.Cache.DeletePrefix(c.Request.Context(), "auth:sess:"+hash(raw))
}

func (s *Server) invalidateRecall(c *gin.Context, accountID string) {
	_ = s.Cache.DeletePrefix(c.Request.Context(), "recall:"+accountID+":")
}
