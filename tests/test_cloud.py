"""Tests for the cloud pipeline, run fully offline (LocalStore + SQLite + fake Azure OpenAI client)."""

import json
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from modelaudit.cli import main
from modelaudit.cloud.explain import AzureOpenAIExplainer, RuleExplainer, build_messages, parse_reply
from modelaudit.cloud.pipeline import process_batch
from modelaudit.cloud.records import run_id_for
from modelaudit.cloud.sinks import SqliteSink
from modelaudit.cloud.store import INPUTS, REPORTS, LocalStore, check_name, parse_submit_path


@pytest.fixture
def batch_files(tmp_path):
    """A small market and a look-ahead strategy (weights use tomorrow's return), so checks fail."""
    rng = np.random.default_rng(3)
    dates = pd.bdate_range("2018-01-01", periods=900)
    tickers = [f"S{i:02d}" for i in range(20)]
    rets = pd.DataFrame(rng.normal(0.0003, 0.015, (len(dates), len(tickers))), dates, tickers)
    closes = 100 * (1 + rets).cumprod()
    weights = np.sign(rets.shift(-1)).fillna(0) / len(tickers)
    prices = closes.stack().rename("close").reset_index()
    prices.columns = ["date", "ticker", "close"]
    pos = weights.stack().rename("weight").reset_index()
    pos.columns = ["date", "ticker", "weight"]
    prices_path, pos_path = tmp_path / "p.csv", tmp_path / "w.csv"
    prices.to_csv(prices_path, index=False)
    pos.to_csv(pos_path, index=False)
    return prices_path, pos_path


class FakeOpenAI:
    """Stands in for openai.OpenAI: returns a canned reply and records the request."""

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = self.reply(kwargs) if callable(self.reply) else self.reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _ai_reply(kwargs):
    flagged = json.loads(kwargs["messages"][1]["content"])["flagged_checks"]
    return json.dumps({"explanations": [{"check_key": c["check_key"], "explanation": f"AI on {c['check_key']}",
                                         "suggested_action": "Fix it."} for c in flagged]})


def _stage(root, batch_files, client="acme", batch="b1"):
    main(["stage", "--root", str(root), "--client", client, "--batch", batch,
          "--prices", str(batch_files[0]), "--positions", str(batch_files[1]), "--name", "Leaky L/S"])


def test_submit_path_parsing_and_name_safety():
    assert parse_submit_path("audit-inputs/acme/2026-11-18/submit.json") == ("acme", "2026-11-18")
    assert parse_submit_path("acme/2026-11-18/submit.json") == ("acme", "2026-11-18")
    assert parse_submit_path("audit-inputs/acme/2026-11-18/prices.csv") is None
    for bad in ("..", "a/b", "", "-x", "a" * 70):
        with pytest.raises(ValueError):
            check_name(bad, "client")


def test_local_store_blocks_path_escape(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).write_bytes(INPUTS, "../../evil.txt", b"x", "text/plain")


def test_pipeline_end_to_end_writes_reports_and_rows(tmp_path, batch_files):
    _stage(tmp_path, batch_files)
    sink = SqliteSink(tmp_path / "results.db")
    outcome = process_batch(LocalStore(tmp_path), sink, RuleExplainer(), "acme", "b1")

    assert outcome.verdict == "FAIL"
    reports = tmp_path / REPORTS / "acme" / "b1"
    assert {"report.html", "results.json", "explanations.json"} <= {p.name for p in reports.iterdir()}
    with sqlite3.connect(tmp_path / "results.db") as conn:
        run = conn.execute("SELECT strategy, verdict, n_fail FROM runs").fetchone()
        n_checks = conn.execute("SELECT COUNT(*) FROM check_results").fetchone()[0]
        lookahead = conn.execute("SELECT status FROM check_results WHERE check_key='lookahead'").fetchone()[0]
        n_expl = conn.execute("SELECT COUNT(*) FROM explanations").fetchone()[0]
    assert run[0] == "Leaky L/S" and run[1] == "FAIL" and run[2] >= 1
    assert n_checks == 7 and lookahead == "FAIL"
    assert n_expl == len(outcome.explanations) >= 1


def test_rerunning_a_batch_replaces_rows_instead_of_duplicating(tmp_path, batch_files):
    _stage(tmp_path, batch_files)
    sink = SqliteSink(tmp_path / "results.db")
    for _ in range(2):
        process_batch(LocalStore(tmp_path), sink, RuleExplainer(), "acme", "b1")
    with sqlite3.connect(tmp_path / "results.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM check_results").fetchone()[0] == 7


def test_bad_input_is_recorded_as_error_not_raised(tmp_path, batch_files):
    _stage(tmp_path, batch_files)
    (tmp_path / INPUTS / "acme" / "b1" / "positions.csv").write_text("date,ticker,size\n2020-01-01,A,1\n")
    outcome = process_batch(LocalStore(tmp_path), SqliteSink(tmp_path / "r.db"), RuleExplainer(), "acme", "b1")
    assert outcome.verdict == "ERROR" and "weight" in outcome.error
    assert (tmp_path / REPORTS / "acme" / "b1" / "error.json").exists()
    with sqlite3.connect(tmp_path / "r.db") as conn:
        assert conn.execute("SELECT verdict FROM runs").fetchone()[0] == "ERROR"


def test_missing_file_is_an_input_error(tmp_path, batch_files):
    _stage(tmp_path, batch_files)
    (tmp_path / INPUTS / "acme" / "b1" / "prices.csv").unlink()
    outcome = process_batch(LocalStore(tmp_path), SqliteSink(tmp_path / "r.db"), RuleExplainer(), "acme", "b1")
    assert outcome.verdict == "ERROR" and "prices.csv" in outcome.error


def test_azure_openai_explainer_uses_model_reply(tmp_path, batch_files):
    _stage(tmp_path, batch_files)
    fake = FakeOpenAI(reply=_ai_reply)
    explainer = AzureOpenAIExplainer("https://x.openai.azure.com", "gpt-test", client=fake)
    outcome = process_batch(LocalStore(tmp_path), SqliteSink(tmp_path / "r.db"), explainer, "acme", "b1")
    assert all(e["explanation"].startswith("AI on") for e in outcome.explanations)
    request = fake.calls[0]
    assert request["model"] == "gpt-test" and request["response_format"] == {"type": "json_object"}
    # Only summary numbers go to the model, never raw prices or positions.
    assert "prices.csv" not in request["messages"][1]["content"]
    with sqlite3.connect(tmp_path / "r.db") as conn:
        assert conn.execute("SELECT DISTINCT model FROM explanations").fetchone()[0] == "azure-openai:gpt-test"


@pytest.mark.parametrize("fake", [FakeOpenAI(error=RuntimeError("503")), FakeOpenAI(reply="not json"),
                                  FakeOpenAI(reply='{"explanations": []}')])
def test_azure_openai_failures_fall_back_to_rules(tmp_path, batch_files, fake):
    _stage(tmp_path, batch_files)
    explainer = AzureOpenAIExplainer("https://x.openai.azure.com", "gpt-test", client=fake)
    outcome = process_batch(LocalStore(tmp_path), SqliteSink(tmp_path / "r.db"), explainer, "acme", "b1")
    assert outcome.explanations and not any(e["explanation"].startswith("AI on") for e in outcome.explanations)
    assert explainer.model == "rules (fallback)"


def test_parse_reply_rejects_unexpected_or_empty_items():
    good = {"check_key": "costs", "explanation": "x", "suggested_action": "y"}
    assert parse_reply(json.dumps({"explanations": [good]}), {"costs"}) == [good]
    with pytest.raises(ValueError):
        parse_reply(json.dumps({"explanations": [dict(good, explanation=" ")]}), {"costs"})
    with pytest.raises(ValueError):
        parse_reply(json.dumps({"explanations": [dict(good, check_key="other")]}), {"costs"})


def test_prompt_contains_only_flagged_checks():
    result = {"strategy": "s", "verdict": "FAIL", "headline": {}, "gates": {"labels": {}, "cost_bps": 10},
              "checks": [{"key": "costs", "title": "t", "status": "FAIL", "summary": "s", "metrics": {}},
                         {"key": "risk", "title": "t", "status": "PASS", "summary": "s", "metrics": {}}]}
    payload = json.loads(build_messages(result)[1]["content"])
    assert [c["check_key"] for c in payload["flagged_checks"]] == ["costs"]
    assert "labels" not in payload["gates"]


def test_cli_pipeline_and_export(tmp_path, batch_files):
    _stage(tmp_path, batch_files)
    assert main(["pipeline", "--root", str(tmp_path), "--client", "acme", "--batch", "b1"]) == 2
    out = tmp_path / "pbi"
    main(["export", "--db", str(tmp_path / "results.db"), "--out", str(out)])
    runs = pd.read_csv(out / "runs.csv")
    assert runs.loc[0, "run_id"] == run_id_for("acme", "b1")


# ---------- gate suggestions (Foundry) ----------

def test_suggested_gates_are_validated_and_bounded(batch_files):
    from modelaudit.cloud.suggest import suggest_gates
    from modelaudit.data import load_positions, load_prices

    reply = json.dumps({"gates": {"periods_per_year": 252, "max_abs_daily_move": 0.3, "folds": 999,
                                  "lookahead_max_sharpe": 100, "benchmark_ticker": "NOT_THERE",
                                  "cost_bps": "ten"},
                        "reasons": {"max_abs_daily_move": "p99 move is 4%", "folds": "x"}})
    fake = FakeOpenAI(reply=reply)
    gates, reasons, prof = suggest_gates(load_prices(batch_files[0]), load_positions(batch_files[1]), fake, "m")
    assert gates.max_abs_daily_move == 0.3 and gates.periods_per_year == 252
    assert gates.folds == 5                      # out of bounds -> default kept
    assert gates.lookahead_max_sharpe == 4.0     # not tunable by the model -> default kept
    assert gates.benchmark_ticker is None and gates.cost_bps == 10.0
    assert set(reasons) == {"max_abs_daily_move"}
    assert prof["n_tickers"] == 20
    assert len(fake.calls[0]["messages"][1]["content"]) < 3000  # a profile, not the 18,000 data rows


# ---------- the Azure Function handlers, with a stand-in for azure.functions ----------

def _load_function_app(monkeypatch, tmp_path):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    fake = types.ModuleType("azure.functions")

    class FunctionApp:
        def function_name(self, name):
            return lambda f: f

        def blob_trigger(self, **kwargs):
            assert kwargs["source"] == "EventGrid" and kwargs["connection"] == "AuditStorage"
            return lambda f: f

        def route(self, **kwargs):
            return lambda f: f

    class HttpResponse:
        def __init__(self, body, status_code=200, mimetype=None):
            self.body, self.status_code = body, status_code

    fake.FunctionApp, fake.HttpResponse = FunctionApp, HttpResponse
    fake.AuthLevel = SimpleNamespace(FUNCTION="function")
    fake.InputStream = fake.HttpRequest = object
    azure_pkg = types.ModuleType("azure")
    azure_pkg.functions = fake
    monkeypatch.setitem(sys.modules, "azure", azure_pkg)
    monkeypatch.setitem(sys.modules, "azure.functions", fake)
    path = Path(__file__).resolve().parents[1] / "azure" / "function_app" / "function_app.py"
    spec = importlib.util.spec_from_file_location("function_app_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._components = (LocalStore(tmp_path), SqliteSink(tmp_path / "r.db"), RuleExplainer())
    return module


def test_blob_trigger_audits_only_submit_files(monkeypatch, tmp_path, batch_files):
    app = _load_function_app(monkeypatch, tmp_path)
    _stage(tmp_path, batch_files)
    app.audit_on_submit(SimpleNamespace(name="audit-inputs/acme/b1/prices.csv"))
    assert not (tmp_path / REPORTS).exists()
    app.audit_on_submit(SimpleNamespace(name="audit-inputs/acme/b1/submit.json"))
    assert (tmp_path / REPORTS / "acme" / "b1" / "report.html").exists()


def test_http_trigger_runs_batch_and_rejects_bad_requests(monkeypatch, tmp_path, batch_files):
    app = _load_function_app(monkeypatch, tmp_path)
    _stage(tmp_path, batch_files)
    ok = app.run_audit_http(SimpleNamespace(get_json=lambda: {"client": "acme", "batch": "b1"}))
    assert ok.status_code == 200 and json.loads(ok.body)["verdict"] == "FAIL"
    bad = app.run_audit_http(SimpleNamespace(get_json=lambda: {"client": "../x", "batch": "b1"}))
    assert bad.status_code == 400
    missing = app.run_audit_http(SimpleNamespace(get_json=lambda: {}))
    assert missing.status_code == 400


def test_memory_sink_for_fabric_is_idempotent(tmp_path, batch_files):
    from modelaudit.cloud.sinks import MemorySink

    _stage(tmp_path, batch_files)
    sink = MemorySink()
    for _ in range(2):
        process_batch(LocalStore(tmp_path), sink, RuleExplainer(), "acme", "b1")
    tables = sink.tables()
    assert len(tables["runs"]) == 1 and len(tables["check_results"]) == 7
