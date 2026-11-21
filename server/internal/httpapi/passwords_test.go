package httpapi

import (
	"context"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"strings"
	"testing"

	"golang.org/x/crypto/bcrypt"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
)

// Fixed argon2id hash for password "long-enough" (params match the former Python Hub).
const legacyArgon2 = "$argon2id$v=19$m=65536,t=3,p=4$iDStID8zd9immTbvsyDNlQ$ShyjGfR3NLR1cCA9NP59YJo+jJO4DwWm9PnXDzTnSnQ"

func TestHealthNextStepBeforeSignup(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	res, err := http.Get(ts.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	body := readBody(res)
	if res.StatusCode != 200 || !strings.Contains(body, `"next_step":"signup"`) || !strings.Contains(body, `"admin_bootstrapped":false`) {
		t.Fatalf("fresh health %s", body)
	}
	res, err = http.Get(ts.URL + "/api/candidate/status")
	if err != nil {
		t.Fatal(err)
	}
	body = readBody(res)
	if !strings.Contains(body, `"onboarding_url":"/onboarding"`) || !strings.Contains(body, `"source":"missing"`) {
		t.Fatalf("status %s", body)
	}
}

func TestJobsRequireCandidateDetail(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = postJSON(t, client, ts.URL+"/api/jobs", `{"company":"Acme","title":"Engineer","status":"discovered"}`, csrf)
	body := readBody(res)
	if res.StatusCode != 409 || !strings.Contains(body, `"code":"candidate_required"`) || !strings.Contains(body, `"onboarding_url":"/onboarding"`) {
		t.Fatalf("gate %d %s", res.StatusCode, body)
	}
}

func TestMetaIncludesRegistry(t *testing.T) {
	ts := testServer(t)
	defer ts.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar}
	res := postJSON(t, client, ts.URL+"/api/auth/signup", `{"username":"ada","password":"long-enough"}`, "")
	csrf := res.Header.Get("X-CSRF")
	res.Body.Close()
	res = putBody(t, client, ts.URL+"/api/candidate", "text/yaml", "name: Jordan Lee\nemail: jordan@lee.test\ntitles:\n  - Engineer\nlocations:\n  - Remote\n", csrf)
	res.Body.Close()
	res, err := client.Get(ts.URL + "/api/meta")
	if err != nil {
		t.Fatal(err)
	}
	body := readBody(res)
	if res.StatusCode != 200 || !strings.Contains(body, `"registry":"/api/registry/skills"`) {
		t.Fatalf("meta %d %s", res.StatusCode, body)
	}
}

func TestLoginAcceptsLegacyArgon2AndBcrypt(t *testing.T) {
	if !checkPassword(legacyArgon2, "long-enough") || checkPassword(legacyArgon2, "nope") || checkPassword("!locked", "long-enough") {
		t.Fatal("legacy argon2id hash did not verify")
	}
	fresh, err := hashPassword("long-enough")
	if err != nil || !strings.HasPrefix(fresh, "$argon2id$v=19$m=65536,t=3,p=4$") || !checkPassword(fresh, "long-enough") {
		t.Fatalf("new hash %s %v", fresh, err)
	}
	old, err := bcrypt.GenerateFromPassword([]byte("long-enough"), bcrypt.MinCost)
	if err != nil || !checkPassword(string(old), "long-enough") {
		t.Fatal("bcrypt")
	}

	db := store.NewMemory()
	if err := db.CreateAccount(context.Background(), store.Account{
		ID: "acc_py", Username: "ada", PasswordHash: legacyArgon2, CreatedAt: now(),
	}, store.User{
		ID: "usr_py", AccountID: "acc_py", Kind: "admin", DisplayName: "ada", Metadata: []byte("{}"), CreatedAt: now(),
	}); err != nil {
		t.Fatal(err)
	}
	ts := httptest.NewServer(New(config.Config{}, db, blob.NewMemory(), cache.NewMemory(), realtime.New()).Router())
	defer ts.Close()
	res := postJSON(t, http.DefaultClient, ts.URL+"/api/auth/login", `{"username":"ada","password":"long-enough"}`, "")
	if res.StatusCode != 200 {
		t.Fatalf("login %d %s", res.StatusCode, readBody(res))
	}
	res.Body.Close()
}
