package httpapi

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"strconv"
	"strings"

	"golang.org/x/crypto/argon2"
	"golang.org/x/crypto/bcrypt"
)

// New passwords use the same argon2id parameters as the Python hub.
// Existing bcrypt hashes still verify.
func hashPassword(pw string) (string, error) {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	sum := argon2.IDKey([]byte(pw), salt, 3, 64*1024, 4, 32)
	return fmt.Sprintf("$argon2id$v=19$m=65536,t=3,p=4$%s$%s",
		base64.RawStdEncoding.EncodeToString(salt),
		base64.RawStdEncoding.EncodeToString(sum)), nil
}

func checkPassword(hash, pw string) bool {
	if hash == "" || strings.HasPrefix(hash, "!") || pw == "" {
		return false
	}
	if strings.HasPrefix(hash, "$argon2") {
		return verifyArgon2(hash, pw)
	}
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(pw)) == nil
}

func verifyArgon2(encoded, password string) bool {
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || parts[2] != "v=19" {
		return false
	}
	var memory, timeCost uint32
	var threads uint8
	for _, field := range strings.Split(parts[3], ",") {
		key, val, ok := strings.Cut(field, "=")
		n, err := strconv.ParseUint(val, 10, 32)
		if !ok || err != nil || n == 0 {
			return false
		}
		switch key {
		case "m":
			memory = uint32(n)
		case "t":
			timeCost = uint32(n)
		case "p":
			if n > 255 {
				return false
			}
			threads = uint8(n)
		default:
			return false
		}
	}
	if memory == 0 || timeCost == 0 || threads == 0 {
		return false
	}
	salt, err := base64.RawStdEncoding.DecodeString(parts[4])
	if err != nil || len(salt) == 0 {
		return false
	}
	want, err := base64.RawStdEncoding.DecodeString(parts[5])
	if err != nil || len(want) == 0 {
		return false
	}
	var got []byte
	switch parts[1] {
	case "argon2id":
		got = argon2.IDKey([]byte(password), salt, timeCost, memory, threads, uint32(len(want)))
	case "argon2i":
		got = argon2.Key([]byte(password), salt, timeCost, memory, threads, uint32(len(want)))
	default:
		return false
	}
	return subtle.ConstantTimeCompare(got, want) == 1
}
