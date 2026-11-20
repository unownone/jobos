// Package blob is the object-storage seam. Drivers: memory, filesystem, and
// any S3-compatible endpoint (MinIO in tests, AWS S3 or R2 in production).
package blob

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

var ErrNotFound = errors.New("blob not found")

type Object struct {
	Key         string
	Content     []byte
	ContentType string
	Filename    string
	UpdatedAt   string
}

type Store interface {
	Name() string
	Put(ctx context.Context, account, key string, content []byte, contentType, filename string) error
	Get(ctx context.Context, account, key string) (Object, error)
	Delete(ctx context.Context, account, key string) error
}

type Settings struct {
	Driver       string
	Root         string
	Endpoint     string
	Region       string
	Bucket       string
	AccessKey    string
	SecretKey    string
	UsePathStyle bool
}

func Open(s Settings) (Store, error) {
	switch strings.ToLower(strings.TrimSpace(s.Driver)) {
	case "", "memory", "mem":
		return NewMemory(), nil
	case "filesystem", "fs", "file":
		return NewFilesystem(s.Root)
	case "s3", "minio":
		return NewS3(s)
	default:
		return nil, fmt.Errorf("unknown BLOB_DRIVER %q", s.Driver)
	}
}

func safeKey(key string) (string, error) {
	text := strings.TrimPrefix(strings.TrimSpace(key), "/")
	if text == "" || strings.Contains(text, "..") || strings.Contains(text, "\\") {
		return "", fmt.Errorf("invalid blob key")
	}
	return text, nil
}

type meta struct {
	Key         string `json:"key"`
	ContentType string `json:"content_type"`
	Filename    string `json:"filename"`
	UpdatedAt   string `json:"updated_at"`
}

func stamp() string { return time.Now().UTC().Format(time.RFC3339) }

type Memory struct {
	mu    sync.Mutex
	items map[string]Object
}

func NewMemory() *Memory { return &Memory{items: map[string]Object{}} }

func (m *Memory) Name() string { return "memory" }

func (m *Memory) Put(_ context.Context, account, key string, content []byte, contentType, filename string) error {
	k, err := safeKey(key)
	if err != nil {
		return err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.items[account+"\x00"+k] = Object{
		Key: k, Content: append([]byte(nil), content...), ContentType: contentType, Filename: filename, UpdatedAt: stamp(),
	}
	return nil
}

func (m *Memory) Get(_ context.Context, account, key string) (Object, error) {
	k, err := safeKey(key)
	if err != nil {
		return Object{}, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	obj, ok := m.items[account+"\x00"+k]
	if !ok {
		return Object{}, ErrNotFound
	}
	obj.Content = append([]byte(nil), obj.Content...)
	return obj, nil
}

func (m *Memory) Delete(_ context.Context, account, key string) error {
	k, err := safeKey(key)
	if err != nil {
		return err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.items, account+"\x00"+k)
	return nil
}

type Filesystem struct{ root string }

func NewFilesystem(root string) (*Filesystem, error) {
	if root == "" {
		return nil, fmt.Errorf("BLOB_ROOT is required for the filesystem driver")
	}
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	return &Filesystem{root: root}, nil
}

func (f *Filesystem) Name() string { return "filesystem" }

func (f *Filesystem) paths(account, key string) (string, string, error) {
	k, err := safeKey(key)
	if err != nil {
		return "", "", err
	}
	if account == "" || strings.Contains(account, "..") {
		return "", "", fmt.Errorf("invalid account")
	}
	data := filepath.Join(f.root, account, filepath.FromSlash(k))
	return data, data + ".meta.json", nil
}

func (f *Filesystem) Put(_ context.Context, account, key string, content []byte, contentType, filename string) error {
	data, metaPath, err := f.paths(account, key)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(data), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(data, content, 0o644); err != nil {
		return err
	}
	k, _ := safeKey(key)
	raw, _ := json.Marshal(meta{Key: k, ContentType: contentType, Filename: filename, UpdatedAt: stamp()})
	return os.WriteFile(metaPath, raw, 0o644)
}

func (f *Filesystem) Get(_ context.Context, account, key string) (Object, error) {
	data, metaPath, err := f.paths(account, key)
	if err != nil {
		return Object{}, err
	}
	body, err := os.ReadFile(data)
	if err != nil {
		if os.IsNotExist(err) {
			return Object{}, ErrNotFound
		}
		return Object{}, err
	}
	obj := Object{Content: body, ContentType: "application/octet-stream"}
	if raw, err := os.ReadFile(metaPath); err == nil {
		var m meta
		if json.Unmarshal(raw, &m) == nil {
			obj.Key = m.Key
			obj.ContentType = m.ContentType
			obj.Filename = m.Filename
			obj.UpdatedAt = m.UpdatedAt
		}
	}
	return obj, nil
}

func (f *Filesystem) Delete(_ context.Context, account, key string) error {
	data, metaPath, err := f.paths(account, key)
	if err != nil {
		return err
	}
	_ = os.Remove(metaPath)
	err = os.Remove(data)
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

type S3 struct {
	client *s3.Client
	bucket string
}

func NewS3(s Settings) (*S3, error) {
	if s.Bucket == "" || s.AccessKey == "" || s.SecretKey == "" {
		return nil, fmt.Errorf("S3_BUCKET, S3_ACCESS_KEY, and S3_SECRET_KEY are required")
	}
	region := s.Region
	if region == "" {
		region = "us-east-1"
	}
	client := s3.New(s3.Options{
		Region:       region,
		BaseEndpoint: aws.String(s.Endpoint),
		UsePathStyle: s.UsePathStyle,
		Credentials:  credentials.NewStaticCredentialsProvider(s.AccessKey, s.SecretKey, ""),
	})
	if s.Endpoint == "" {
		client = s3.New(s3.Options{
			Region:      region,
			Credentials: credentials.NewStaticCredentialsProvider(s.AccessKey, s.SecretKey, ""),
		})
	}
	return &S3{client: client, bucket: s.Bucket}, nil
}

func (s *S3) Name() string { return "s3" }

func (s *S3) objectKey(account, key string) (string, error) {
	k, err := safeKey(key)
	if err != nil {
		return "", err
	}
	return account + "/" + k, nil
}

func (s *S3) Put(ctx context.Context, account, key string, content []byte, contentType, filename string) error {
	objKey, err := s.objectKey(account, key)
	if err != nil {
		return err
	}
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	_, err = s.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(s.bucket),
		Key:         aws.String(objKey),
		Body:        bytes.NewReader(content),
		ContentType: aws.String(contentType),
		Metadata: map[string]string{
			"filename": filename,
		},
	})
	return err
}

func (s *S3) Get(ctx context.Context, account, key string) (Object, error) {
	objKey, err := s.objectKey(account, key)
	if err != nil {
		return Object{}, err
	}
	out, err := s.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(objKey),
	})
	if err != nil {
		if strings.Contains(err.Error(), "NoSuchKey") || strings.Contains(err.Error(), "NotFound") || strings.Contains(err.Error(), "404") {
			return Object{}, ErrNotFound
		}
		return Object{}, err
	}
	defer out.Body.Close()
	body, err := io.ReadAll(out.Body)
	if err != nil {
		return Object{}, err
	}
	ctype := "application/octet-stream"
	if out.ContentType != nil {
		ctype = *out.ContentType
	}
	k, _ := safeKey(key)
	return Object{Key: k, Content: body, ContentType: ctype, Filename: out.Metadata["filename"]}, nil
}

func (s *S3) Delete(ctx context.Context, account, key string) error {
	objKey, err := s.objectKey(account, key)
	if err != nil {
		return err
	}
	_, err = s.client.DeleteObject(ctx, &s3.DeleteObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(objKey),
	})
	return err
}
