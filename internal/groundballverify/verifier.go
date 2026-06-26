package groundballverify

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

const DefaultQuestion = "who had the most RBIs in 1962"
const DefaultEvalCase = "stat_rbi_1962"

type Config struct {
	BaseURL          string
	Question         string
	ExpectedEvalCase string
	Client           *http.Client
}

type Report struct {
	OK       bool     `json:"ok"`
	BaseURL  string   `json:"base_url"`
	Question string   `json:"question"`
	Checks   []Check  `json:"checks"`
	Failures []string `json:"failures,omitempty"`
}

type Check struct {
	Name   string `json:"name"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail,omitempty"`
}

func Verify(ctx context.Context, cfg Config) (Report, error) {
	baseURL := strings.TrimRight(cfg.BaseURL, "/")
	if baseURL == "" {
		baseURL = "http://127.0.0.1:8000"
	}
	question := cfg.Question
	if question == "" {
		question = DefaultQuestion
	}
	expectedEvalCase := cfg.ExpectedEvalCase
	if expectedEvalCase == "" && question == DefaultQuestion {
		expectedEvalCase = DefaultEvalCase
	}
	client := cfg.Client
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}

	report := Report{
		OK:       true,
		BaseURL:  baseURL,
		Question: question,
	}

	if err := verifyHealth(ctx, client, baseURL, &report); err != nil {
		return report, err
	}
	if err := verifySources(ctx, client, baseURL, &report); err != nil {
		return report, err
	}
	if err := verifyQuery(ctx, client, baseURL, question, expectedEvalCase, &report); err != nil {
		return report, err
	}
	report.OK = len(report.Failures) == 0
	return report, nil
}

func verifyHealth(ctx context.Context, client *http.Client, baseURL string, report *Report) error {
	var payload map[string]any
	if err := getJSON(ctx, client, baseURL+"/health/verification", &payload); err != nil {
		return err
	}
	failures := []string{}
	if stringField(payload, "status") != "ok" {
		failures = append(failures, "health status is not ok")
	}
	checks, ok := payload["checks"].([]any)
	if !ok || len(checks) == 0 {
		failures = append(failures, "health checks are missing")
	} else {
		for _, raw := range checks {
			check, ok := raw.(map[string]any)
			if !ok {
				failures = append(failures, "health check has invalid shape")
				continue
			}
			if stringField(check, "status") != "ok" {
				name := stringField(check, "name")
				failures = append(failures, fmt.Sprintf("health check %q is not ok", name))
			}
		}
	}
	addCheck(report, "health_verification", failures, "operational verification is ready")
	return nil
}

func verifySources(ctx context.Context, client *http.Client, baseURL string, report *Report) error {
	var payload map[string]any
	if err := getJSON(ctx, client, baseURL+"/sources", &payload); err != nil {
		return err
	}
	failures := []string{}
	dataset, _ := payload["dataset"].(map[string]any)
	if stringField(dataset, "name") != "NeuML/baseballdata" {
		failures = append(failures, "sources dataset is not NeuML/baseballdata")
	}
	files, ok := payload["files"].([]any)
	if !ok || len(files) == 0 {
		failures = append(failures, "sources files are missing")
	} else if !anyFileHasSHA(files) {
		failures = append(failures, "sources files do not expose sha256")
	}
	addCheck(report, "sources_manifest", failures, "dataset manifest exposes files and checksums")
	return nil
}

func verifyQuery(
	ctx context.Context,
	client *http.Client,
	baseURL string,
	question string,
	expectedEvalCase string,
	report *Report,
) error {
	var payload map[string]any
	body := map[string]any{"question": question, "answer_mode": "stats_only"}
	if err := postJSON(ctx, client, baseURL+"/query", body, &payload); err != nil {
		return err
	}
	failures := []string{}
	if stringField(payload, "intent") != "stat_query" {
		failures = append(failures, "query intent is not stat_query")
	}
	if boolField(payload, "unsupported") {
		failures = append(failures, "query is unsupported")
	}
	if expectedEvalCase == DefaultEvalCase && !defaultAnswerLooksRight(stringField(payload, "answer")) {
		failures = append(failures, "query answer does not include Davis, 153, and RBI")
	}
	sources, ok := payload["sources"].([]any)
	if !ok || len(sources) == 0 {
		failures = append(failures, "query sources are missing")
	} else {
		if !hasGroundedDuckDBSource(sources) {
			failures = append(failures, "query does not expose grounded DuckDB source evidence")
		}
		if expectedEvalCase == DefaultEvalCase && !hasDefaultQueryResultRow(sources) {
			failures = append(failures, "query rows do not include Davis with 153")
		}
	}
	metadata, _ := payload["metadata"].(map[string]any)
	if !boolField(metadata, "sql_visible") {
		failures = append(failures, "query metadata does not mark SQL visible")
	}
	sql, _ := metadata["sql"].(map[string]any)
	if !boolField(sql, "parameterized") {
		failures = append(failures, "query metadata does not mark SQL parameterized")
	}
	if expectedEvalCase != "" {
		eval, _ := metadata["eval"].(map[string]any)
		if stringField(eval, "case_id") != expectedEvalCase {
			failures = append(
				failures,
				fmt.Sprintf("query metadata does not match %s eval case", expectedEvalCase),
			)
		}
	}
	addCheck(report, "default_query_contract", failures, "default query exposes grounded evidence")
	return nil
}

func defaultAnswerLooksRight(answer string) bool {
	normalized := strings.ToLower(answer)
	return strings.Contains(normalized, "davis") &&
		strings.Contains(normalized, "153") &&
		strings.Contains(normalized, "rbi")
}

func getJSON(ctx context.Context, client *http.Client, url string, target any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	return doJSON(client, req, target)
}

func postJSON(ctx context.Context, client *http.Client, url string, body any, target any) error {
	encoded, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(encoded))
	if err != nil {
		return err
	}
	req.Header.Set("content-type", "application/json")
	return doJSON(client, req, target)
}

func doJSON(client *http.Client, req *http.Request, target any) error {
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("%s %s returned HTTP %d", req.Method, req.URL.Path, resp.StatusCode)
	}
	if err := json.NewDecoder(resp.Body).Decode(target); err != nil {
		return fmt.Errorf("decode %s %s: %w", req.Method, req.URL.Path, err)
	}
	return nil
}

func addCheck(report *Report, name string, failures []string, detail string) {
	ok := len(failures) == 0
	report.Checks = append(report.Checks, Check{Name: name, OK: ok, Detail: detail})
	for _, failure := range failures {
		report.Failures = append(report.Failures, name+": "+failure)
	}
}

func anyFileHasSHA(files []any) bool {
	for _, raw := range files {
		file, ok := raw.(map[string]any)
		if ok && stringField(file, "sha256") != "" {
			return true
		}
	}
	return false
}

func hasGroundedDuckDBSource(sources []any) bool {
	for _, raw := range sources {
		source, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if stringField(source, "type") != "duckdb" {
			continue
		}
		if stringField(source, "sql") == "" {
			continue
		}
		rows, ok := source["rows"].([]any)
		if !ok || len(rows) == 0 {
			continue
		}
		manifest, _ := source["data_manifest"].(map[string]any)
		if !hasPrimaryLahmanAuthority(manifest) {
			continue
		}
		return true
	}
	return false
}

func hasDefaultQueryResultRow(sources []any) bool {
	for _, rawSource := range sources {
		source, ok := rawSource.(map[string]any)
		if !ok || stringField(source, "type") != "duckdb" {
			continue
		}
		rows, ok := source["rows"].([]any)
		if !ok {
			continue
		}
		for _, rawRow := range rows {
			row, ok := rawRow.(map[string]any)
			if !ok {
				continue
			}
			name := strings.ToLower(stringField(row, "name"))
			if strings.Contains(name, "davis") && numericFieldEquals(row, "stat_value", 153) {
				return true
			}
		}
	}
	return false
}

func hasPrimaryLahmanAuthority(manifest map[string]any) bool {
	authorities, ok := manifest["source_authorities"].([]any)
	if !ok {
		return false
	}
	for _, raw := range authorities {
		authority, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if stringField(authority, "name") == "Lahman" && stringField(authority, "role") == "primary" {
			return true
		}
	}
	return false
}

func stringField(payload map[string]any, key string) string {
	if payload == nil {
		return ""
	}
	value, _ := payload[key].(string)
	return value
}

func boolField(payload map[string]any, key string) bool {
	if payload == nil {
		return false
	}
	value, _ := payload[key].(bool)
	return value
}

func numericFieldEquals(payload map[string]any, key string, expected float64) bool {
	if payload == nil {
		return false
	}
	switch value := payload[key].(type) {
	case float64:
		return value == expected
	case int:
		return float64(value) == expected
	default:
		return false
	}
}
