package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
)

// Redis is optional. Login must verify the store PasswordHash with a Nop cache.
func TestSignupLogoutLoginWithoutRedis(t *testing.T) {
	db := store.NewMemory()
	srv := New(config.Config{}, db, blob.NewMemory(), cache.Nop{}, realtime.New())
	ts := httptest.NewServer(srv.Router())
	defer ts.Close()

	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Jar: jar}

	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	if res.StatusCode != 200 {
		t.Fatalf("signup %d %s", res.StatusCode, readBody(res))
	}
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()

	acc, user, err := db.AccountByUsername(context.Background(), "ada")
	if err != nil {
		t.Fatal(err)
	}
	if acc.PasswordHash == "" {
		t.Fatal("AccountByUsername returned empty PasswordHash from store")
	}
	if user.PasswordHash == "" {
		t.Fatal("admin user PasswordHash empty in store")
	}
	raw, err := json.Marshal(acc)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "password") || strings.Contains(string(raw), acc.PasswordHash) {
		t.Fatalf("json marshal of Account must omit PasswordHash (json:\"-\"), got %s", raw)
	}

	res = postJSON(t, client, ts.URL+"/api/auth/logout", `{}`, csrf)
	if res.StatusCode != 200 {
		t.Fatalf("logout %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()

	res = postJSON(t, client, ts.URL+"/api/auth/login", `{"username":"ada","password":"long-enough"}`, "")
	body := readBody(res)
	if res.StatusCode != 200 {
		t.Fatalf("login without redis %d %s", res.StatusCode, body)
	}
	me, err := client.Get(ts.URL + "/api/auth/me")
	if err != nil {
		t.Fatal(err)
	}
	meBody := readBody(me)
	if me.StatusCode != 200 || !strings.Contains(meBody, `"kind":"admin"`) {
		t.Fatalf("me after login %d %s", me.StatusCode, meBody)
	}
}

func TestLoginRejectsWrongPasswordWithoutRedis(t *testing.T) {
	db := store.NewMemory()
	srv := New(config.Config{}, db, blob.NewMemory(), cache.Nop{}, realtime.New())
	ts := httptest.NewServer(srv.Router())
	defer ts.Close()

	res := postJSON(t, http.DefaultClient, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	if res.StatusCode != 200 {
		t.Fatalf("signup %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()

	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Jar: jar}
	res = postJSON(t, client, ts.URL+"/api/auth/login", `{"username":"ada","password":"wrong-password"}`, "")
	if res.StatusCode != 401 {
		t.Fatalf("want 401 got %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()
}

func TestLoginByEmailWithoutRedis(t *testing.T) {
	db := store.NewMemory()
	srv := New(config.Config{BootstrapToken: "jh_boot_testtoken"}, db, blob.NewMemory(), cache.Nop{}, realtime.New())
	ts := httptest.NewServer(srv.Router())
	defer ts.Close()

	res := postJSON(t, http.DefaultClient, ts.URL+"/api/auth/bootstrap", `{"email":"ada@example.com","password":"long-enough","token":"jh_boot_testtoken"}`, "")
	if res.StatusCode != 200 {
		t.Fatalf("bootstrap %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()

	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Jar: jar}
	res = postJSON(t, client, ts.URL+"/api/auth/login", `{"email":"ada@example.com","password":"long-enough"}`, "")
	body := readBody(res)
	if res.StatusCode != 200 {
		t.Fatalf("email login without redis %d %s", res.StatusCode, body)
	}
	me, err := client.Get(ts.URL + "/api/auth/me")
	if err != nil {
		t.Fatal(err)
	}
	meBody := readBody(me)
	if me.StatusCode != 200 || !strings.Contains(meBody, `"kind":"admin"`) {
		t.Fatalf("me after email login %d %s", me.StatusCode, meBody)
	}
}

func TestCookieSecureFollowsForwardedProtoAndPublicURL(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "http://127.0.0.1/api/auth/login", nil)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = req
	if !cookieSecure(c, "https://hub.example.test") {
		t.Fatal("missing forwarded proto should fall back to https PublicURL")
	}
	if cookieSecure(c, "") {
		t.Fatal("plain HTTP with empty PublicURL must stay non-Secure")
	}
	c.Request.Header.Set("X-Forwarded-Proto", "http")
	if cookieSecure(c, "https://hub.example.test") {
		t.Fatal("X-Forwarded-Proto=http must keep cookies non-Secure even when PublicURL is https")
	}
	c.Request.Header.Set("X-Forwarded-Proto", "https")
	if !cookieSecure(c, "") {
		t.Fatal("X-Forwarded-Proto=https must set Secure cookies")
	}
}

func TestJSONOmitPasswordHashDoesNotBreakStoreLookup(t *testing.T) {
	db := store.NewMemory()
	hash := "$argon2id$v=19$m=65536,t=3,p=4$iDStID8zd9immTbvsyDNlQ$ShyjGfR3NLR1cCA9NP59YJo+jJO4DwWm9PnXDzTnSnQ"
	if err := db.CreateAccount(context.Background(), store.Account{
		ID: "acc_1", Username: "ada", PasswordHash: hash, CreatedAt: now(),
	}, store.User{
		ID: "usr_1", AccountID: "acc_1", Kind: "admin", DisplayName: "ada",
		PasswordHash: hash, Metadata: []byte("{}"), CreatedAt: now(),
	}); err != nil {
		t.Fatal(err)
	}
	acc, _, err := db.AccountByUsername(context.Background(), "ada")
	if err != nil {
		t.Fatal(err)
	}
	// Round-tripping through JSON drops the hash — that must never be the login path.
	blob, _ := json.Marshal(acc)
	var leaked store.Account
	_ = json.Unmarshal(blob, &leaked)
	if leaked.PasswordHash != "" {
		t.Fatal("expected json:\"-\" to drop PasswordHash on marshal")
	}
	if !checkPassword(acc.PasswordHash, "long-enough") {
		t.Fatal("store AccountByUsername must keep PasswordHash for verify; do not JSON-round-trip credentials")
	}
	if checkPassword(leaked.PasswordHash, "long-enough") {
		t.Fatal("JSON-omitted hash must not verify")
	}
}
