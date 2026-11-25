package httpapi

import (
	"encoding/json"
	"fmt"
	"strings"
)

// MCPClientSnippet is a copy-paste block for one AI MCP client.
type MCPClientSnippet struct {
	ID          string `json:"id"`
	Label       string `json:"label"`
	Format      string `json:"format"`
	Filename    string `json:"filename,omitempty"`
	Config      string `json:"config"`
	Instruction string `json:"instruction"`
}

// BuildMCPClientSnippets returns Cursor / Claude / Grok / Codex paste blocks for a Hub MCP URL
// authenticated with a long-lived Hub API key (from invite bootstrap or /api/auth/join).
func BuildMCPClientSnippets(origin, apiKey string) []MCPClientSnippet {
	origin = strings.TrimRight(strings.TrimSpace(origin), "/")
	apiKey = strings.TrimSpace(apiKey)
	mcpURL := origin + "/mcp"
	authNote := "Auth: Bearer API key lasts ~90 days on MCP. Prefer this over short-lived OAuth access tokens; OAuth still works via /connect with refresh (access 24h, refresh 90d)."
	cursorObj := map[string]any{
		"mcpServers": map[string]any{
			"jobos": map[string]any{
				"url": mcpURL,
				"headers": map[string]string{
					"Authorization": "Bearer " + apiKey,
				},
			},
		},
	}
	claudeObj := map[string]any{
		"mcpServers": map[string]any{
			"jobos": map[string]any{
				"type": "http",
				"url":  mcpURL,
				"headers": map[string]string{
					"Authorization": "Bearer " + apiKey,
				},
			},
		},
	}
	grokObj := map[string]any{
		"mcpServers": map[string]any{
			"jobos": map[string]any{
				"transport": "http",
				"url":       mcpURL,
				"headers": map[string]string{
					"Authorization": "Bearer " + apiKey,
				},
			},
		},
	}
	codex := fmt.Sprintf(`[mcp_servers.jobos]
url = %q
http_headers = { Authorization = %q }
`, mcpURL, "Bearer "+apiKey)

	return []MCPClientSnippet{
		{
			ID: "cursor", Label: "Cursor", Format: "json", Filename: "mcp.json",
			Config:      mustPrettyJSON(cursorObj),
			Instruction: "Cursor → Settings → MCP → add from JSON (or merge into ~/.cursor/mcp.json). " + authNote + " Then ask the agent to call get_started.",
		},
		{
			ID: "claude", Label: "Claude", Format: "json", Filename: "claude_desktop_config.json",
			Config:      mustPrettyJSON(claudeObj),
			Instruction: "Claude Desktop / Claude Code: merge into MCP config. " + authNote,
		},
		{
			ID: "grok", Label: "Grok", Format: "json", Filename: "mcp.json",
			Config:      mustPrettyJSON(grokObj),
			Instruction: "Grok / xAI tools: paste as a remote MCP server entry. " + authNote,
		},
		{
			ID: "codex", Label: "Codex", Format: "toml", Filename: "config.toml",
			Config:      codex,
			Instruction: "Codex CLI: merge into ~/.codex/config.toml under mcp_servers. " + authNote,
		},
	}
}

func mustPrettyJSON(v any) string {
	raw, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return "{}"
	}
	return string(raw) + "\n"
}
