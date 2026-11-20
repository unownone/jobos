package cache

import (
	"bufio"
	"context"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestRedisDriverAgainstRESP(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go serveRESP(ln)

	hot, err := Open("redis://"+ln.Addr().String()+"/0", "")
	if err != nil {
		t.Fatal(err)
	}
	if hot.Name() != "redis" {
		t.Fatalf("name %s", hot.Name())
	}
	ctx := context.Background()
	if err := hot.Set(ctx, "jobs:acc:1", []byte("[]"), time.Minute); err != nil {
		t.Fatal(err)
	}
	got, ok, err := hot.Get(ctx, "jobs:acc:1")
	if err != nil || !ok || string(got) != "[]" {
		t.Fatalf("get %q %v %v", got, ok, err)
	}
	if _, ok, err := hot.Get(ctx, "missing"); err != nil || ok {
		t.Fatalf("miss %v %v", ok, err)
	}
	if err := hot.Set(ctx, "jobs:acc:2", []byte("x"), time.Minute); err != nil {
		t.Fatal(err)
	}
	if err := hot.DeletePrefix(ctx, "jobs:acc:"); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := hot.Get(ctx, "jobs:acc:1"); err != nil || ok {
		t.Fatalf("prefix delete left the key %v %v", ok, err)
	}
}

func serveRESP(ln net.Listener) {
	var mu sync.Mutex
	items := map[string]string{}
	for {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		go func(conn net.Conn) {
			defer conn.Close()
			r := bufio.NewReader(conn)
			for {
				cmd, err := readArray(r)
				if err != nil {
					return
				}
				if len(cmd) == 0 {
					return
				}
				mu.Lock()
				reply := dispatch(items, cmd)
				mu.Unlock()
				if _, err := conn.Write([]byte(reply)); err != nil {
					return
				}
			}
		}(conn)
	}
}

func dispatch(items map[string]string, cmd []string) string {
	switch strings.ToUpper(cmd[0]) {
	case "SET":
		if len(cmd) < 3 {
			return "-ERR\r\n"
		}
		items[cmd[1]] = cmd[2]
		return "+OK\r\n"
	case "GET":
		value, ok := items[cmd[1]]
		if !ok {
			return "$-1\r\n"
		}
		return "$" + strconv.Itoa(len(value)) + "\r\n" + value + "\r\n"
	case "DEL":
		n := 0
		for _, key := range cmd[1:] {
			if _, ok := items[key]; ok {
				delete(items, key)
				n++
			}
		}
		return ":" + strconv.Itoa(n) + "\r\n"
	case "SCAN":
		prefix := ""
		for i := 1; i < len(cmd)-1; i++ {
			if strings.EqualFold(cmd[i], "MATCH") {
				prefix = strings.TrimSuffix(cmd[i+1], "*")
			}
		}
		var keys []string
		for key := range items {
			if prefix == "" || strings.HasPrefix(key, prefix) {
				keys = append(keys, key)
			}
		}
		body := "*2\r\n$1\r\n0\r\n*" + strconv.Itoa(len(keys)) + "\r\n"
		for _, key := range keys {
			body += "$" + strconv.Itoa(len(key)) + "\r\n" + key + "\r\n"
		}
		return body
	case "PING":
		return "+PONG\r\n"
	case "HELLO":
		return "*14\r\n$6\r\nserver\r\n$5\r\nredis\r\n$7\r\nversion\r\n$5\r\n7.2.0\r\n$5\r\nproto\r\n:2\r\n$2\r\nid\r\n:1\r\n$4\r\nmode\r\n$10\r\nstandalone\r\n$4\r\nrole\r\n$6\r\nmaster\r\n$7\r\nmodules\r\n*0\r\n"
	case "AUTH", "CLIENT", "INFO", "SELECT":
		return "+OK\r\n"
	default:
		return "+OK\r\n"
	}
}

func readArray(r *bufio.Reader) ([]string, error) {
	line, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	if !strings.HasPrefix(line, "*") {
		return nil, io.ErrUnexpectedEOF
	}
	n, err := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, "*")))
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, n)
	for i := 0; i < n; i++ {
		head, err := r.ReadString('\n')
		if err != nil {
			return nil, err
		}
		if !strings.HasPrefix(head, "$") {
			return nil, io.ErrUnexpectedEOF
		}
		size, err := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(head, "$")))
		if err != nil {
			return nil, err
		}
		buf := make([]byte, size+2)
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, err
		}
		out = append(out, string(buf[:size]))
	}
	return out, nil
}
