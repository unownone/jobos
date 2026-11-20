package httpapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"strings"
	"testing"

	"golang.org/x/crypto/bcrypt"

	"github.com/unownone/jobos/server/internal/blob"
	"github.com/unownone/jobos/server/internal/cache"
	"github.com/unownone/jobos/server/internal/config"
	"github.com/unownone/jobos/server/internal/realtime"
	"github.com/unownone/jobos/server/internal/store"
)

const pythonArgon2 = "$argon2id$v=19$m=65536,t=3,p=4$iDStID8zd9immTbvsyDNlQ$ShyjGfR3NLR1cCA9NP59YJo+jJO4DwWm9PnXDzTnSnQ"

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

func TestLoginAcceptsPythonArgon2AndBcrypt(t *testing.T) {
	if !checkPassword(pythonArgon2, "long-enough") || checkPassword(pythonArgon2, "nope") || checkPassword("!locked", "long-enough") {
		t.Fatal("python argon2id hash did not verify")
	}
	fresh, err := hashPassword("long-enough")
	if err != nil || !strings.HasPrefix(fresh, "$argon2id$v=19$m=65536,t=3,p=4$") || !checkPassword(fresh, "long-enough") {
		t.Fatalf("new hash %s %v", fresh, err)
	}
	old, err := bcrypt.GenerateFromPassword([]byte("long-enough"), bcrypt.MinCost)
	if err != nil || !checkPassword(string(old), "long-enough") {
		t.Fatal("bcrypt")
	}
	if _, err := exec.LookPath("uv"); err == nil {
		cmd := exec.Command("uv", "run", "--frozen", "python", "-c", "from argon2 import PasswordHasher; import sys; PasswordHasher().verify(sys.argv[1], 'long-enough')", fresh)
		cmd.Dir = "../../../board"
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("python rejected a Go argon2id hash: %v %s", err, out)
		}
	}

	db := store.NewMemory()
	if err := db.CreateAccount(context.Background(), store.Account{
		ID: "acc_py", Username: "ada", PasswordHash: pythonArgon2, CreatedAt: now(),
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
