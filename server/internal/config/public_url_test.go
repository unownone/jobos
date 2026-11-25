package config

import "testing"

func TestPublicURLFromEnvPrefersURLThenHost(t *testing.T) {
	t.Setenv("HUB_PUBLIC_URL", "https://ikr.one/")
	t.Setenv("HUB_PUBLIC_HOST", "ignored.example")
	if got := publicURLFromEnv(); got != "https://ikr.one" {
		t.Fatalf("url %q", got)
	}

	t.Setenv("HUB_PUBLIC_URL", "")
	t.Setenv("HUB_PUBLIC_HOST", "ikr.one")
	if got := publicURLFromEnv(); got != "https://ikr.one" {
		t.Fatalf("bare host %q", got)
	}

	t.Setenv("HUB_PUBLIC_HOST", "127.0.0.1:8787")
	if got := publicURLFromEnv(); got != "http://127.0.0.1:8787" {
		t.Fatalf("local hostport %q", got)
	}

	t.Setenv("HUB_PUBLIC_HOST", "127.0.0.1")
	if got := publicURLFromEnv(); got != "http://127.0.0.1" {
		t.Fatalf("loopback bare %q", got)
	}

	t.Setenv("HUB_PUBLIC_HOST", "129.225.116.58")
	if got := publicURLFromEnv(); got != "http://129.225.116.58" {
		t.Fatalf("bare ipv4 %q", got)
	}

	t.Setenv("HUB_PUBLIC_HOST", "hunt.example.com:443")
	if got := publicURLFromEnv(); got != "https://hunt.example.com" {
		t.Fatalf(":443 host %q", got)
	}

	t.Setenv("HUB_PUBLIC_HOST", "https://jobs.example.com")
	if got := publicURLFromEnv(); got != "https://jobs.example.com" {
		t.Fatalf("full host %q", got)
	}
}
