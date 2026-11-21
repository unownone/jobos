package httpapi

import "strings"

// readyCandidateYAML is a flat profile the SPA can save and the Hub accepts.
const readyCandidateYAML = "name: Ada Lovelace\nemail: ada@lovelace.test\ntitles:\n  - Engineer\nlocations:\n  - Remote\n"

// profileMissing reports the same required fields as the Python Hub:
// a real name, an email, and at least one title and location.
// Flat SPA keys (name, email, titles, locations) and nested identity/target both count.
func profileMissing(text string) string {
	name, email, titles, locations := parseProfile(text)
	var missing []string
	if name == "" || exampleName(name) {
		missing = append(missing, "identity.full_name")
	}
	if email == "" || !strings.Contains(email, "@") || strings.EqualFold(email, "ada@example.com") {
		missing = append(missing, "identity.email")
	}
	if len(titles) == 0 {
		missing = append(missing, "target.titles")
	}
	if len(locations) == 0 {
		missing = append(missing, "target.locations")
	}
	return strings.Join(missing, ", ")
}

func exampleName(name string) bool {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "ada example", "your name":
		return true
	default:
		return false
	}
}

func parseProfile(text string) (name, email string, titles, locations []string) {
	section := ""
	listKey := ""
	for _, line := range strings.Split(text, "\n") {
		if strings.TrimSpace(line) == "" || strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		indent := len(line) - len(strings.TrimLeft(line, " "))
		trim := strings.TrimSpace(line)
		if strings.HasPrefix(trim, "- ") {
			item := strings.Trim(strings.TrimSpace(trim[2:]), `"'`)
			if item == "" {
				continue
			}
			switch listKey {
			case "titles":
				titles = append(titles, item)
			case "locations":
				locations = append(locations, item)
			}
			continue
		}
		key, value, ok := strings.Cut(trim, ":")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.Trim(strings.TrimSpace(value), `"'`)
		if indent == 0 {
			section = ""
			listKey = ""
			switch key {
			case "identity", "target":
				section = key
			case "name", "full_name":
				name = value
			case "email":
				email = value
			case "titles", "locations":
				listKey = key
				appendList(&titles, &locations, key, value)
			}
			continue
		}
		switch section {
		case "identity":
			switch key {
			case "full_name", "name":
				if value != "" {
					name = value
				}
			case "email":
				email = value
			}
		case "target":
			switch key {
			case "titles", "locations":
				listKey = key
				appendList(&titles, &locations, key, value)
			}
		}
	}
	return name, email, titles, locations
}

func appendList(titles, locations *[]string, key, value string) {
	if value == "" {
		return
	}
	var dst *[]string
	switch key {
	case "titles":
		dst = titles
	case "locations":
		dst = locations
	default:
		return
	}
	for _, part := range strings.Split(value, ",") {
		part = strings.TrimSpace(part)
		if part != "" {
			*dst = append(*dst, part)
		}
	}
}
