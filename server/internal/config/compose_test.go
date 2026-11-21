package config

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

var coolifyForbidden = []string{"`", "$(", "${", "|", "&", ";", "\n", "\r", "\t", ">", "<"}

var namedVolume = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]*$`)

func repoRoot(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Clean(filepath.Join(wd, "../../.."))
	if _, err := os.Stat(filepath.Join(root, "docker-compose.yml")); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestComposeCoolifyContract(t *testing.T) {
	root := repoRoot(t)
	files := []string{
		"docker-compose.yml",
		"docker-compose.plain.yml",
		"docker-compose.traefik.yml",
		"board/docker-compose.yml",
	}
	for _, rel := range files {
		raw, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			t.Fatalf("%s: %v", rel, err)
		}
		text := string(raw)
		if strings.Contains(text, "\nrabbitmq:") || strings.Contains(text, "\n  rabbitmq:") {
			t.Fatalf("%s still declares rabbitmq", rel)
		}
		for _, source := range serviceVolumeSources(text) {
			for _, needle := range coolifyForbidden {
				if strings.Contains(source, needle) {
					t.Fatalf("%s volume source %q contains %q", rel, source, needle)
				}
			}
		}
		for _, entry := range serviceVolumeEntries(text) {
			if !strings.Contains(entry, "/var/lib/postgresql/data") && !strings.Contains(entry, "/var/lib/jobos/blobs") {
				continue
			}
			source := volumeSource(entry)
			if strings.HasPrefix(source, "/") || strings.HasPrefix(source, ".") || strings.HasPrefix(source, "~") {
				t.Fatalf("%s durable mount uses bind %q", rel, source)
			}
			if !namedVolume.MatchString(source) {
				t.Fatalf("%s durable mount %q is not a named volume", rel, source)
			}
		}
	}
	rootCompose, err := os.ReadFile(filepath.Join(root, "docker-compose.yml"))
	if err != nil {
		t.Fatal(err)
	}
	text := string(rootCompose)
	if !strings.Contains(text, `DATABASE_URL: "${DATABASE_URL:-}"`) && !strings.Contains(text, "DATABASE_URL: ${DATABASE_URL:-}") {
		t.Fatalf("root compose DATABASE_URL must pass through empty default")
	}
	for _, needle := range []string{"services:", "api:", "web:", "postgres:", "profiles:", "redis:", "minio:"} {
		if !strings.Contains(text, needle) {
			t.Fatalf("root compose missing %s", needle)
		}
	}
	example, err := os.ReadFile(filepath.Join(root, "board/.env.example"))
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range strings.Split(string(example), "\n") {
		trim := strings.TrimSpace(line)
		if trim == "" || strings.HasPrefix(trim, "#") || !strings.Contains(trim, "=") {
			continue
		}
		key, value, _ := strings.Cut(trim, "=")
		if strings.TrimSpace(key) == "DATABASE_URL" && strings.TrimSpace(value) != "" {
			t.Fatalf("board/.env.example must not set DATABASE_URL, got %q", value)
		}
	}
}

func serviceVolumeEntries(text string) []string {
	var out []string
	inVolumes := false
	volumesIndent := -1
	for _, line := range strings.Split(text, "\n") {
		if trimmed := strings.TrimSpace(line); trimmed == "volumes:" {
			inVolumes = true
			volumesIndent = leadingSpaces(line)
			continue
		}
		if !inVolumes {
			continue
		}
		indent := leadingSpaces(line)
		trim := strings.TrimSpace(line)
		if trim == "" || strings.HasPrefix(trim, "#") {
			continue
		}
		if indent <= volumesIndent && !strings.HasPrefix(trim, "-") {
			inVolumes = false
			continue
		}
		if strings.HasPrefix(trim, "- ") {
			out = append(out, strings.TrimPrefix(trim, "- "))
		}
	}
	return out
}

func serviceVolumeSources(text string) []string {
	var out []string
	for _, entry := range serviceVolumeEntries(text) {
		out = append(out, volumeSource(entry))
	}
	return out
}

func leadingSpaces(line string) int {
	n := 0
	for _, r := range line {
		if r == ' ' {
			n++
			continue
		}
		break
	}
	return n
}

func volumeSource(entry string) string {
	entry = strings.Trim(entry, `"'`)
	if strings.HasPrefix(entry, "source:") {
		return strings.Trim(strings.TrimPrefix(entry, "source:"), ` "'`)
	}
	if i := strings.Index(entry, ":"); i > 0 {
		return strings.Trim(entry[:i], `"'`)
	}
	return entry
}
