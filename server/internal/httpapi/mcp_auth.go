package httpapi

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/agentflow"
)

// resolveMCPGrant accepts OAuth access tokens (jhmcp_at_…) or Hub API keys (jh_agt_… / jh_own_…).
// API keys are preferred for invite paste configs — they map to a 90-day MCP grant.
// Hub keys are always re-checked against the DB so revocation sticks even if an in-memory grant exists.
func (s *Server) resolveMCPGrant(c *gin.Context, token string) (agentflow.Grant, string) {
	token = strings.TrimSpace(token)
	if token == "" {
		return agentflow.Grant{}, "invalid_token"
	}
	if strings.HasPrefix(token, "jh_boot_") || strings.HasPrefix(token, "jh_inv_") {
		return agentflow.Grant{}, "invalid_token"
	}
	if strings.HasPrefix(token, "jh_agt_") || strings.HasPrefix(token, "jh_own_") {
		key, err := s.DB.APIKeyByHash(c.Request.Context(), hash(token))
		if err != nil || key.RevokedAt != "" {
			return agentflow.Grant{}, "invalid_token"
		}
		user, err := s.DB.User(c.Request.Context(), key.UserID)
		if err != nil || user.DisabledAt != "" {
			return agentflow.Grant{}, "invalid_token"
		}
		label := user.DisplayName
		if label == "" {
			label = key.Prefix
		}
		return s.flow().EnsureHubKeyGrant(user.AccountID, user.ID, label, token), ""
	}
	if grant, reason := s.flow().GrantForAccess(token); reason == "" {
		return grant, ""
	}
	return agentflow.Grant{}, "invalid_token"
}

func (s *Server) principalFromGrant(c *gin.Context, grant agentflow.Grant) (principal, error) {
	if grant.UserID == "" {
		return principal{}, errString("grant has no user")
	}
	user, err := s.DB.User(c.Request.Context(), grant.UserID)
	if err != nil {
		return principal{}, err
	}
	if user.DisabledAt != "" {
		return principal{}, errString("user disabled")
	}
	return principalFromUser(user, "mcp", ""), nil
}

func mcpWWWAuthenticate(origin string) string {
	return `Bearer realm="jobos", resource_metadata="` + origin + `/.well-known/oauth-protected-resource/mcp", scope="jobos"`
}

func (s *Server) mcpUnauthorized(c *gin.Context, reason string) {
	origin := strings.TrimRight(s.publicURL(c), "/")
	c.Header("WWW-Authenticate", mcpWWWAuthenticate(origin))
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusUnauthorized, gin.H{"error": reason})
}
