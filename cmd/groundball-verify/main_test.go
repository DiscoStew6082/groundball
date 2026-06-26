package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"testing"
)

func TestRunWritesJSONReportAndHonorsFlags(t *testing.T) {
	client := &http.Client{
		Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			switch r.URL.Path {
			case "/health/verification":
				return jsonResponse(t, http.StatusOK, map[string]any{
					"status": "ok",
					"checks": []map[string]any{{"name": "data_manifest", "status": "ok"}},
				}), nil
			case "/sources":
				return jsonResponse(t, http.StatusOK, map[string]any{
					"dataset": map[string]any{"name": "NeuML/baseballdata"},
					"files":   []map[string]any{{"path": "data/Batting.csv", "sha256": "abc123"}},
				}), nil
			case "/query":
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Fatalf("decode query body: %v", err)
				}
				if body["question"] != "custom deterministic question" {
					t.Fatalf("question = %v", body["question"])
				}
				return jsonResponse(t, http.StatusOK, map[string]any{
					"intent":      "stat_query",
					"unsupported": false,
					"sources": []map[string]any{
						{
							"type": "duckdb",
							"sql":  "SELECT * FROM batting WHERE yearID = ?",
							"rows": []map[string]any{{"name": "Davis, Tommy", "stat_value": 153}},
							"data_manifest": map[string]any{
								"source_authorities": []map[string]any{
									{"name": "Lahman", "role": "primary"},
								},
							},
						},
					},
					"metadata": map[string]any{
						"sql_visible": true,
						"sql":         map[string]any{"parameterized": true},
						"eval":        map[string]any{"case_id": "stat_rbi_1962"},
					},
				}), nil
			default:
				return jsonResponse(t, http.StatusNotFound, map[string]any{}), nil
			}
		}),
	}
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	code := run(
		context.Background(),
		[]string{
			"--base-url", "http://groundball.test/",
			"--question", "custom deterministic question",
			"--json",
		},
		&stdout,
		&stderr,
		client,
	)

	if code != 0 {
		t.Fatalf("exit code = %d, stderr = %s", code, stderr.String())
	}
	var report map[string]any
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		t.Fatalf("decode stdout JSON: %v\nstdout = %s", err, stdout.String())
	}
	if report["ok"] != true {
		t.Fatalf("report ok = %v", report["ok"])
	}
	if report["base_url"] != "http://groundball.test" {
		t.Fatalf("base_url = %v", report["base_url"])
	}
	if report["question"] != "custom deterministic question" {
		t.Fatalf("question = %v", report["question"])
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return fn(req)
}

func jsonResponse(t *testing.T, status int, value any) *http.Response {
	t.Helper()
	var body bytes.Buffer
	if err := json.NewEncoder(&body).Encode(value); err != nil {
		t.Fatalf("encode json response: %v", err)
	}
	return &http.Response{
		StatusCode: status,
		Header:     http.Header{"content-type": []string{"application/json"}},
		Body:       io.NopCloser(&body),
	}
}
