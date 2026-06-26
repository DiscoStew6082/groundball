package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"

	"github.com/DiscoStew6082/groundball/internal/groundballverify"
)

func main() {
	os.Exit(run(context.Background(), os.Args[1:], os.Stdout, os.Stderr, nil))
}

func run(
	ctx context.Context,
	args []string,
	stdout io.Writer,
	stderr io.Writer,
	client *http.Client,
) int {
	flags := flag.NewFlagSet("groundball-verify", flag.ContinueOnError)
	flags.SetOutput(stderr)
	baseURL := flags.String("base-url", "http://127.0.0.1:8000", "Groundball API base URL")
	question := flags.String(
		"question",
		groundballverify.DefaultQuestion,
		"deterministic query used for the API contract check",
	)
	expectedEvalCase := flags.String(
		"expected-eval-case",
		"",
		"optional eval manifest case expected for the query; defaults for the built-in query",
	)
	jsonOutput := flags.Bool("json", false, "write the full verification report as JSON")
	if err := flags.Parse(args); err != nil {
		return 2
	}

	report, err := groundballverify.Verify(ctx, groundballverify.Config{
		BaseURL:          *baseURL,
		Question:         *question,
		ExpectedEvalCase: *expectedEvalCase,
		Client:           client,
	})
	if err != nil {
		fmt.Fprintf(stderr, "groundball-verify: %v\n", err)
		return 2
	}

	if *jsonOutput {
		encoder := json.NewEncoder(stdout)
		encoder.SetIndent("", "  ")
		if err := encoder.Encode(report); err != nil {
			fmt.Fprintf(stderr, "groundball-verify: write JSON report: %v\n", err)
			return 2
		}
	} else {
		writeTextReport(stdout, report)
	}

	if !report.OK {
		return 1
	}
	return 0
}

func writeTextReport(stdout io.Writer, report groundballverify.Report) {
	status := "PASS"
	if !report.OK {
		status = "FAIL"
	}
	fmt.Fprintf(stdout, "Groundball verify: %s\n", status)
	fmt.Fprintf(stdout, "API: %s\n", report.BaseURL)
	fmt.Fprintf(stdout, "Question: %s\n", report.Question)
	for _, check := range report.Checks {
		marker := "ok"
		if !check.OK {
			marker = "fail"
		}
		fmt.Fprintf(stdout, "- %s: %s", check.Name, marker)
		if check.Detail != "" {
			fmt.Fprintf(stdout, " - %s", check.Detail)
		}
		fmt.Fprintln(stdout)
	}
	for _, failure := range report.Failures {
		fmt.Fprintf(stdout, "  failure: %s\n", failure)
	}
}
