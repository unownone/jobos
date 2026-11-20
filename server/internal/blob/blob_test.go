package blob

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path"
	"strings"
	"sync"
	"testing"
)

func TestFilesystemRoundTrip(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(Settings{Driver: "filesystem", Root: dir})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := store.Put(ctx, "acc", "candidate-resume.pdf", []byte("%PDF"), "application/pdf", "resume.pdf"); err != nil {
		t.Fatal(err)
	}
	obj, err := store.Get(ctx, "acc", "candidate-resume.pdf")
	if err != nil || string(obj.Content) != "%PDF" || obj.ContentType != "application/pdf" || obj.Filename != "resume.pdf" {
		t.Fatalf("get %#v %v", obj, err)
	}
	if err := store.Delete(ctx, "acc", "candidate-resume.pdf"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Get(ctx, "acc", "candidate-resume.pdf"); err != ErrNotFound {
		t.Fatalf("deleted get %v", err)
	}
	if _, err := os.Stat(dir + "/acc/candidate-resume.pdf"); !os.IsNotExist(err) {
		t.Fatalf("file remains %v", err)
	}
}

func TestS3PathStyleRoundTrip(t *testing.T) {
	var mu sync.Mutex
	objects := map[string][]byte{}
	types := map[string]string{}
	buckets := map[string]bool{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
		if len(parts) == 0 || parts[0] == "" {
			http.NotFound(w, r)
			return
		}
		bucket := parts[0]
		key := ""
		if len(parts) > 1 {
			key = path.Join(parts[1:]...)
		}
		mu.Lock()
		defer mu.Unlock()
		switch r.Method {
		case http.MethodHead:
			if !buckets[bucket] {
				http.Error(w, "missing", http.StatusNotFound)
				return
			}
			w.WriteHeader(http.StatusOK)
		case http.MethodPut:
			if key == "" {
				buckets[bucket] = true
				w.WriteHeader(http.StatusOK)
				return
			}
			body, _ := io.ReadAll(r.Body)
			objects[bucket+"/"+key] = body
			types[bucket+"/"+key] = r.Header.Get("Content-Type")
			buckets[bucket] = true
			w.WriteHeader(http.StatusOK)
		case http.MethodGet:
			body, ok := objects[bucket+"/"+key]
			if !ok {
				w.Header().Set("Content-Type", "application/xml")
				w.WriteHeader(http.StatusNotFound)
				_, _ = w.Write([]byte(`<Error><Code>NoSuchKey</Code></Error>`))
				return
			}
			w.Header().Set("Content-Type", types[bucket+"/"+key])
			_, _ = w.Write(body)
		case http.MethodDelete:
			delete(objects, bucket+"/"+key)
			w.WriteHeader(http.StatusNoContent)
		default:
			http.Error(w, r.Method, http.StatusMethodNotAllowed)
		}
	}))
	defer srv.Close()

	store, err := Open(Settings{
		Driver: "s3", Endpoint: srv.URL, Bucket: "jobos", AccessKey: "jobos", SecretKey: "jobossecret", UsePathStyle: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	ready, ok := store.(interface{ EnsureBucket(context.Context) error })
	if !ok {
		t.Fatal("s3 store should create its bucket")
	}
	ctx := context.Background()
	if err := ready.EnsureBucket(ctx); err != nil {
		t.Fatal(err)
	}
	if err := store.Put(ctx, "acc", "candidate.yaml", []byte("name: Ada\n"), "text/yaml", "candidate.yaml"); err != nil {
		t.Fatal(err)
	}
	obj, err := store.Get(ctx, "acc", "candidate.yaml")
	if err != nil || string(obj.Content) != "name: Ada\n" {
		t.Fatalf("get %#v %v", obj, err)
	}
	if _, err := store.Get(ctx, "acc", "missing.txt"); err != ErrNotFound {
		t.Fatalf("missing %v", err)
	}
	if err := store.Delete(ctx, "acc", "candidate.yaml"); err != nil {
		t.Fatal(err)
	}
}
