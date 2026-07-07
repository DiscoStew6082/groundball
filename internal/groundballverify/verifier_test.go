package groundballverify

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestVerifyAcceptsHealthyGroundballAPIContract(t *testing.T) {
	client := &http.Client{
		Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			var payload any
			switch r.URL.Path {
			case "/health/verification":
				if r.Method != http.MethodGet {
					t.Fatalf("health method = %s, want GET", r.Method)
				}
				payload = map[string]any{
					"status": "ok",
					"checks": []map[string]any{
						{"name": "data_manifest", "status": "ok"},
						{"name": "duckdb_core_tables", "status": "ok"},
						{"name": "guardrail_manifest", "status": "ok"},
					},
					"commands": map[string]any{"eval_gate": "uv run python -m evals.questions"},
				}
			case "/sources":
				if r.Method != http.MethodGet {
					t.Fatalf("sources method = %s, want GET", r.Method)
				}
				payload = map[string]any{
					"dataset": map[string]any{"name": "NeuML/baseballdata"},
					"files": []map[string]any{
						{"path": "data/Batting.csv", "sha256": "abc123"},
					},
				}
			case "/query":
				if r.Method != http.MethodPost {
					t.Fatalf("query method = %s, want POST", r.Method)
				}
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Fatalf("decode query body: %v", err)
				}
				if body["question"] != "who had the most RBIs in 1962" {
					t.Fatalf("question = %v", body["question"])
				}
				payload = map[string]any{
					"answer":             "Davis, Tommy: 153 RBI",
					"intent":             "stat_query",
					"unsupported":        false,
					"unsupported_reason": nil,
					"review_reason":      nil,
					"review":             nil,
					"warnings":           []any{},
					"sources": []map[string]any{
						{
							"type": "duckdb",
							"sql":  "SELECT * FROM batting WHERE yearID = ?",
							"rows": []map[string]any{{"name": "Davis, Tommy", "stat_value": 153}},
							"data_manifest": map[string]any{
								"dataset": map[string]any{"name": "NeuML/baseballdata"},
								"source_authorities": []map[string]any{
									{"name": "Lahman", "role": "primary"},
								},
							},
						},
					},
					"metadata": map[string]any{
						"route":       "stat_query",
						"sql_visible": true,
						"sql":         map[string]any{"parameterized": true, "row_count": 1},
						"eval":        map[string]any{"case_id": "stat_rbi_1962"},
					},
				}
			default:
				return jsonResponse(t, http.StatusNotFound, map[string]any{"error": "not found"}), nil
			}
			return jsonResponse(t, http.StatusOK, payload), nil
		}),
	}

	report, err := Verify(context.Background(), Config{
		BaseURL: "http://groundball.test",
		Client:  client,
	})
	if err != nil {
		t.Fatalf("Verify returned error: %v", err)
	}
	if !report.OK {
		t.Fatalf("report.OK = false, failures = %#v", report.Failures)
	}
	if len(report.Checks) != 3 {
		t.Fatalf("checks length = %d, want 3", len(report.Checks))
	}
}

func TestVerifyDefaultsToNonConflictingLocalAPIBaseURL(t *testing.T) {
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
				return jsonResponse(t, http.StatusOK, map[string]any{
					"answer":      "Davis, Tommy: 153 RBI",
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
				return jsonResponse(t, http.StatusNotFound, map[string]any{"error": "not found"}), nil
			}
		}),
	}

	report, err := Verify(context.Background(), Config{Client: client})
	if err != nil {
		t.Fatalf("Verify returned error: %v", err)
	}
	if report.BaseURL != "http://127.0.0.1:8001" {
		t.Fatalf("BaseURL = %q, want http://127.0.0.1:8001", report.BaseURL)
	}
}

func TestVerifyReportsActionableContractFailures(t *testing.T) {
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
				return jsonResponse(t, http.StatusOK, map[string]any{
					"answer":      "Someone else led MLB with 1 RBI.",
					"intent":      "stat_query",
					"unsupported": false,
					"sources": []map[string]any{
						{
							"type":          "duckdb",
							"sql":           "SELECT * FROM batting WHERE yearID = ?",
							"rows":          []map[string]any{{"name": "Wrong Player", "stat_value": 1}},
							"data_manifest": map[string]any{"source_authorities": []map[string]any{{"name": "Lahman", "role": "primary"}}},
						},
					},
					"metadata": map[string]any{
						"sql_visible": false,
						"sql":         map[string]any{"parameterized": false},
						"eval":        map[string]any{"case_id": "different_case"},
					},
				}), nil
			default:
				return jsonResponse(t, http.StatusNotFound, map[string]any{}), nil
			}
		}),
	}

	report, err := Verify(context.Background(), Config{
		BaseURL: "http://groundball.test",
		Client:  client,
	})
	if err != nil {
		t.Fatalf("Verify returned error: %v", err)
	}
	if report.OK {
		t.Fatalf("report.OK = true, want false")
	}
	assertFailureContains(t, report, "default_query_contract: query answer does not include Davis, 153, and RBI")
	assertFailureContains(t, report, "default_query_contract: query rows do not include Davis with 153")
	assertFailureContains(t, report, "default_query_contract: query metadata does not mark SQL visible")
	assertFailureContains(t, report, "default_query_contract: query metadata does not match stat_rbi_1962 eval case")
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

func assertFailureContains(t *testing.T, report Report, want string) {
	t.Helper()
	for _, failure := range report.Failures {
		if strings.Contains(failure, want) {
			return
		}
	}
	t.Fatalf("failure containing %q not found in %#v", want, report.Failures)
}
