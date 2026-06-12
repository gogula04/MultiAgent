"""Enterprise web UI for the verification automation pipeline."""

from __future__ import annotations

import argparse
import html
import json
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import AppConfig
from .orchestrator import VerificationOrchestrator


DEFAULT_PORT = 8787


@dataclass
class UIState:
    busy: bool = False
    has_run: bool = False
    last_request: dict[str, Any] = field(default_factory=dict)
    last_result: dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass
class UIRuntime:
    config: AppConfig
    default_requirement: str
    default_text: str
    default_snippet: str
    default_output_dir: Path
    default_mode: str
    default_require_review: bool
    default_use_graph: bool
    auto_run: bool
    state: UIState = field(default_factory=UIState)

    @property
    def orchestrator(self) -> VerificationOrchestrator:
        return VerificationOrchestrator(config=self.config)

    def launch_payload(self, form: dict[str, str] | None = None) -> dict[str, Any]:
        form = form or {}
        requirement = form.get("requirement", self.default_requirement).strip()
        text = form.get("text", self.default_text).strip()
        snippet = form.get("snippet", self.default_snippet).strip()
        mode = form.get("mode", self.default_mode).strip() or self.default_mode
        repo_root = Path(form.get("repo_root", str(self.config.repo_root))).expanduser()
        output_dir = Path(form.get("output_dir", str(self.default_output_dir))).expanduser()
        require_review = form.get("require_review", "on" if self.default_require_review else "") in {"on", "1", "true", "True"}
        use_graph = form.get("use_graph", "on" if self.default_use_graph else "") in {"on", "1", "true", "True"}
        return {
            "requirement": requirement,
            "text": text,
            "snippet": snippet,
            "repo_root": str(repo_root),
            "output_dir": str(output_dir),
            "mode": mode,
            "require_review": require_review,
            "use_graph": use_graph,
        }

    def start_run(self, payload: dict[str, Any]) -> bool:
        with self.state.lock:
            if self.state.busy:
                return False
            self.state.busy = True
            self.state.has_run = True
            self.state.last_error = ""
            self.state.last_request = payload
            self.state.last_result = {}
            self.state.started_at = time.time()
            self.state.finished_at = 0.0

        thread = threading.Thread(target=self._run_pipeline, args=(payload,), daemon=True)
        thread.start()
        return True

    def _run_pipeline(self, payload: dict[str, Any]) -> None:
        try:
            config = replace(
                self.config,
                repo_root=Path(payload["repo_root"]),
                auto_approve=not bool(payload["require_review"]),
            )
            orchestrator = VerificationOrchestrator(config=config)
            result = orchestrator.run_to_directory(
                requirement_identifier=payload["requirement"],
                requirement_text=payload["text"],
                source_snippet=payload["snippet"],
                output_dir=Path(payload["output_dir"]),
                mode_override=payload["mode"],
            )
            with self.state.lock:
                self.state.last_result = dict(result)
                self.state.last_error = ""
                self.state.finished_at = time.time()
        except Exception as exc:  # pragma: no cover - defensive for runtime UI
            with self.state.lock:
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                self.state.last_result = {}
                self.state.finished_at = time.time()
        finally:
            with self.state.lock:
                self.state.busy = False


class VerificationUIHandler(BaseHTTPRequestHandler):
    runtime: UIRuntime

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/download":
            self._serve_download(parsed.query)
            return
        if parsed.path == "/api/state":
            self._serve_json(self._state_snapshot())
            return
        self._serve_index()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = {key: values[-1] for key, values in urllib.parse.parse_qs(body).items()}
        payload = self.runtime.launch_payload(form)
        accepted = self.runtime.start_run(payload)
        if not accepted:
            self._send_plain("A run is already in progress.", status=HTTPStatus.CONFLICT)
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _serve_index(self) -> None:
        self._send_html(self._render_page())

    def _render_page(self) -> str:
        state = self._state_snapshot()
        config = self.runtime.config
        request = state["last_request"] if isinstance(state.get("last_request"), dict) else {}
        has_run = bool(state.get("has_run"))
        last_result = state["last_result"] if has_run else {}
        artifacts = last_result.get("artifacts", {}) if isinstance(last_result, dict) else {}
        logs = last_result.get("logs", []) if isinstance(last_result, dict) else []
        rapita = last_result.get("rapita", {}) if isinstance(last_result, dict) else {}
        proof = last_result.get("proof_report", {}) if isinstance(last_result, dict) else {}
        resolved_requirement = last_result.get("resolved_requirement", {}) if isinstance(last_result, dict) else {}
        review_status_value = str(last_result.get("review_status", "")) if isinstance(last_result, dict) else ""
        review_notes_value = str(last_result.get("review_notes", "")) if isinstance(last_result, dict) else ""
        review_decision = last_result.get("review_decision", {}) if isinstance(last_result, dict) else {}

        busy = state["busy"]
        meta_refresh = '<meta http-equiv="refresh" content="2">' if busy else ""
        requirement = html.escape(str(request.get("requirement", self.runtime.default_requirement or "")))
        text = html.escape(str(request.get("text", self.runtime.default_text or "")))
        snippet = html.escape(str(request.get("snippet", self.runtime.default_snippet or "")))
        repo_root = html.escape(str(config.repo_root))
        output_dir = html.escape(str(self.runtime.default_output_dir))
        selected_mode = html.escape(str(request.get("mode", self.runtime.default_mode or "Auto")))
        review_checked = "checked" if self.runtime.default_require_review else ""
        graph_checked = "checked" if self.runtime.default_use_graph else ""
        auto_badge = "Auto-run enabled" if self.runtime.auto_run else "Manual launch"
        status_label = self._compute_status_label(last_result, busy)
        poolside_badge = "Connected" if config.poolside_base_url and config.poolside_api_key else "Local mode"
        if review_status_value == "approved" and not self.runtime.default_require_review:
            review_status_text = "auto-approved draft"
        elif review_status_value:
            review_status_text = review_status_value.replace("_", " ")
        else:
            review_status_text = "pending review" if self.runtime.default_require_review else "auto-approved draft"
        review_status = html.escape(review_status_text)
        review_notes = html.escape(review_notes_value)
        proof_summary = html.escape(str(proof.get("summary", ""))) if proof else ""
        proof_conclusion = html.escape(str(proof.get("conclusion", ""))) if proof else ""
        learning_summary = html.escape(str(last_result.get("learning_summary_text", ""))) if isinstance(last_result, dict) else ""
        learning_status_value = str(last_result.get("learning_status", "")) if isinstance(last_result, dict) else ""
        coverage = proof.get("coverage", []) if proof else []
        test_results = proof.get("test_results", {}) if proof else {}
        review_decision_summary = ""
        if isinstance(review_decision, dict):
            review_decision_summary = html.escape(str(review_decision.get("summary", "")))

        artifact_cards = []
        for name, path in artifacts.items():
            artifact_cards.append(
                f"""
                <a class="artifact" href="/download?artifact={urllib.parse.quote(name)}" target="_blank" rel="noreferrer">
                  <div class="artifact-name">{html.escape(name)}</div>
                  <div class="artifact-path">{html.escape(str(path))}</div>
                </a>
                """
            )
        artifact_html = "\n".join(artifact_cards) if artifact_cards else '<div class="muted">Artifacts will appear here after a run.</div>'
        mapping_rows = last_result.get("mappings", []) if isinstance(last_result, dict) else []
        mapping_html = self._render_mapping_rows(mapping_rows)
        resolved_html = self._render_resolution_summary(resolved_requirement)

        log_lines = "".join(f"<div class='log-line'>{html.escape(str(line))}</div>" for line in logs[-12:]) or "<div class='empty-state'>Run execution to see logs, triage output, and coverage evidence.</div>"
        coverage_lines = "".join(
            f"<div class='coverage-row'><span>{html.escape(str(item.get('item', 'coverage')))}</span><span>{html.escape(str(item.get('status', 'unknown')))}</span></div>"
            for item in coverage
        ) or "<div class='empty-state'>Coverage evidence appears after a verification run.</div>"

        test_status = "not run"
        if isinstance(test_results, dict):
            if test_results.get("passed"):
                test_status = f"{test_results.get('executed', 0)} passed"
            else:
                if test_results:
                    test_status = f"{test_results.get('failed', 0)} failed"

        current_status = last_result.get("status", "") if isinstance(last_result, dict) else ""
        if busy:
            steps = [
                ("Intake", "done"),
                ("Discovery", "done"),
                ("Parsing", "done"),
                ("Mapping", "done"),
                ("Strategy", "done"),
                ("Drafts", "done"),
                ("Review", "done" if review_status_value == "approved" else "pending"),
                ("Execution", "pending"),
                ("Coverage", "pending"),
                ("Proof", "pending"),
                ("Learning", "pending"),
            ]
        elif current_status == "blocked":
            steps = [
                ("Intake", "blocked"),
                ("Discovery", "ready"),
                ("Parsing", "ready"),
                ("Mapping", "ready"),
                ("Strategy", "ready"),
                ("Drafts", "ready"),
                ("Review", "ready"),
                ("Execution", "ready"),
                ("Coverage", "ready"),
                ("Proof", "ready"),
                ("Learning", "done" if last_result.get("learning_status") == "recorded" else "pending"),
            ]
        elif last_result:
            steps = [
                ("Intake", "done"),
                ("Discovery", "done"),
                ("Parsing", "done"),
                ("Mapping", "done"),
                ("Strategy", "done"),
                ("Drafts", "done" if artifacts else "ready"),
                ("Review", "done" if review_status_value == "approved" else "pending"),
                ("Execution", "done" if test_results else "ready"),
                ("Coverage", "done" if coverage else "ready"),
                ("Proof", "done" if proof else "ready"),
                ("Learning", "done" if last_result.get("learning_status") == "recorded" else "ready"),
            ]
        else:
            steps = [
                ("Intake", "ready"),
                ("Discovery", "ready"),
                ("Parsing", "ready"),
                ("Mapping", "ready"),
                ("Strategy", "ready"),
                ("Drafts", "ready"),
                ("Review", "ready"),
                ("Execution", "ready"),
                ("Coverage", "ready"),
                ("Proof", "ready"),
                ("Learning", "ready"),
            ]
        step_html = "".join(
            f"<div class='step {status}'><span>{html.escape(label)}</span><small>{html.escape(status.replace('_', ' '))}</small></div>"
            for label, status in steps
        )

        if last_result:
            result_section = f"""
              <section class="panel panel-soft">
                <div class="panel-heading">
                  <h2>Run Summary</h2>
                  <span class="chip {('green' if isinstance(test_results, dict) and test_results.get('passed') else 'amber') if isinstance(test_results, dict) and test_results else ('amber' if last_result.get('status') == 'blocked' else 'muted')}">{html.escape(status_label)}</span>
                </div>
                <div class="metric-grid">
                  <div class="metric"><span>Mode</span><strong>{html.escape(str(last_result.get('mode', selected_mode) if isinstance(last_result, dict) else selected_mode))}</strong></div>
                  <div class="metric"><span>Review</span><strong>{html.escape(review_status)}</strong></div>
                  <div class="metric"><span>Tests</span><strong>{html.escape(test_status)}</strong></div>
                  <div class="metric"><span>Rapita</span><strong>{html.escape(str(rapita.get('summary', 'Skipped') if rapita else 'Skipped'))}</strong></div>
                </div>
                <div class="subgrid">
                  <div class="subpanel">
                    <h3>Requirement Resolution</h3>
                    {resolved_html}
                  </div>
                  <div class="subpanel">
                    <h3>Proof</h3>
                    <p>{proof_summary or "Run the pipeline to generate a proof report."}</p>
                  </div>
                </div>
                <div class="subpanel full">
                  <h3>Conclusion</h3>
                  <p>{proof_conclusion or "The evidence package will appear here after execution."}</p>
                </div>
                <div class="subpanel full">
                  <h3>Learning Agent</h3>
                  <p>{learning_summary or "Learning memory will be recorded from verified, blocked, or failed runs."}</p>
                  <p class="muted">Status: {html.escape(learning_status_value or "not recorded")}</p>
                </div>
              </section>
            """
        else:
            result_section = """
              <section class="panel panel-soft">
                <div class="panel-heading">
                  <h2>Run Summary</h2>
                  <span class="chip muted">Ready</span>
                </div>
                <div class="empty-state large">Enter a requirement and launch verification to generate drafts, execute tests, and produce evidence.</div>
              </section>
            """

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Verification Automation</title>
  {meta_refresh}
  <style>
    :root {{
      --bg: #07111f;
      --bg2: #0b1728;
      --panel: rgba(14, 24, 38, 0.92);
      --panel2: rgba(18, 29, 47, 0.88);
      --line: rgba(160, 184, 214, 0.16);
      --text: #eaf1ff;
      --muted: #a1b0c8;
      --accent: #78a6ff;
      --accent2: #8df0d8;
      --warn: #f5c16c;
      --good: #6fe3a3;
      --shadow: 0 20px 60px rgba(0, 0, 0, 0.38);
      --radius: 22px;
      --radius-sm: 16px;
      --radius-xs: 12px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(120, 166, 255, 0.28), transparent 30%),
        radial-gradient(circle at top right, rgba(141, 240, 216, 0.18), transparent 28%),
        linear-gradient(160deg, var(--bg), var(--bg2) 70%);
      min-height: 100vh;
    }}
    .shell {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 28px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 22px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .logo {{
      width: 44px;
      height: 44px;
      border-radius: 14px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      box-shadow: 0 10px 28px rgba(120, 166, 255, 0.34);
    }}
    .brand h1 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.02em;
    }}
    .brand p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .status-row {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
      background: rgba(255,255,255,0.04);
      color: var(--text);
      font-size: 13px;
      text-decoration: none;
    }}
    .chip.green {{ color: #c8ffe1; border-color: rgba(111, 227, 163, 0.32); }}
    .chip.amber {{ color: #ffe1a6; border-color: rgba(245, 193, 108, 0.32); }}
    .chip.muted {{ color: var(--muted); }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(340px, 420px) 1fr;
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      background: linear-gradient(180deg, var(--panel), rgba(10, 18, 30, 0.96));
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .panel-soft {{
      padding: 22px;
    }}
    .panel-heading {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
    }}
    .panel-heading h2,
    .subpanel h3 {{
      margin: 0;
      font-size: 15px;
      letter-spacing: -0.01em;
    }}
    .form {{
      padding: 22px;
    }}
    .field {{
      margin-bottom: 14px;
    }}
    .field label {{
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 8px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .field input,
    .field textarea {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(160,184,214,0.16);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 13px 14px;
      outline: none;
      font: inherit;
    }}
    .field select {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(160,184,214,0.16);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 13px 14px;
      outline: none;
      font: inherit;
    }}
    .field select {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(160,184,214,0.16);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 13px 14px;
      outline: none;
      font: inherit;
    }}
    .field textarea {{
      min-height: 118px;
      resize: vertical;
      line-height: 1.5;
    }}
    .field input:focus,
    .field textarea:focus {{
      border-color: rgba(120, 166, 255, 0.7);
      box-shadow: 0 0 0 4px rgba(120, 166, 255, 0.16);
    }}
    .checkbox-row {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin: 14px 0 18px;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid rgba(160,184,214,0.16);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      font-size: 14px;
    }}
    .check input {{
      accent-color: var(--accent);
      width: 16px;
      height: 16px;
    }}
    .button-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 6px;
    }}
    .button {{
      appearance: none;
      border: 0;
      border-radius: 14px;
      padding: 13px 16px;
      font-weight: 700;
      font: inherit;
      cursor: pointer;
      text-decoration: none;
      transition: transform .16s ease, box-shadow .16s ease, opacity .16s ease;
    }}
    .button:hover {{ transform: translateY(-1px); }}
    .button.primary {{
      background: linear-gradient(135deg, var(--accent), #5a78f2);
      color: white;
      box-shadow: 0 12px 30px rgba(90, 120, 242, 0.28);
    }}
    .button.secondary {{
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(160,184,214,0.16);
      color: var(--text);
    }}
    .stack {{
      display: grid;
      gap: 18px;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric {{
      padding: 16px;
      border-radius: var(--radius-sm);
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(160,184,214,0.14);
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .metric strong {{
      font-size: 18px;
      letter-spacing: -0.02em;
    }}
    .subgrid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }}
    .subpanel {{
      border-radius: var(--radius-sm);
      padding: 16px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(160,184,214,0.14);
    }}
    .subpanel.full {{ margin-top: 6px; }}
    .subpanel p {{
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 14px;
    }}
    .section-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin-top: 18px;
    }}
    .artifact-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .artifact {{
      display: block;
      text-decoration: none;
      padding: 14px;
      border-radius: 16px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(160,184,214,0.14);
      color: var(--text);
      min-height: 84px;
    }}
    .artifact:hover {{
      border-color: rgba(120,166,255,0.6);
      background: rgba(120,166,255,0.08);
    }}
    .artifact-name {{
      font-weight: 700;
      margin-bottom: 8px;
      font-size: 14px;
    }}
    .artifact-path {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      word-break: break-word;
    }}
    .timeline {{
      display: grid;
      gap: 8px;
    }}
    .step {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      border-radius: 14px;
      padding: 12px 14px;
      border: 1px solid rgba(160,184,214,0.12);
      background: rgba(255,255,255,0.03);
    }}
    .step.done {{ border-color: rgba(111,227,163,0.28); }}
    .step.ready {{ border-color: rgba(160,184,214,0.12); }}
    .step.pending {{ border-color: rgba(245,193,108,0.28); }}
    .step.blocked {{ border-color: rgba(245,193,108,0.40); background: rgba(245,193,108,0.05); }}
    .step span {{ font-weight: 650; }}
    .step small {{ color: var(--muted); text-transform: capitalize; }}
    .logs {{
      max-height: 280px;
      overflow: auto;
      display: grid;
      gap: 8px;
      padding-right: 4px;
    }}
    .log-line {{
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(160,184,214,0.12);
      color: #d5e1f5;
      font-size: 13px;
      line-height: 1.5;
    }}
    .coverage-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-radius: 12px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(160,184,214,0.12);
      font-size: 13px;
    }}
    .mapping-table {{
      display: grid;
      gap: 10px;
    }}
    .mapping-head {{
      display: grid;
      grid-template-columns: 1.1fr 1fr 1fr 1fr;
      gap: 10px;
      padding: 0 14px 2px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .mapping-row {{
      display: grid;
      grid-template-columns: 1.1fr 1fr 1fr 1fr;
      gap: 10px;
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(160,184,214,0.12);
      font-size: 13px;
    }}
    .mapping-row span {{
      word-break: break-word;
    }}
    .muted {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .empty-state {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
      padding: 8px 2px;
    }}
    .empty-state.large {{
      min-height: 220px;
      display: grid;
      place-items: center;
      text-align: center;
      border-radius: 18px;
      border: 1px dashed rgba(160,184,214,0.18);
      background: rgba(255,255,255,0.02);
      padding: 24px;
    }}
    .footer {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}
    @media (max-width: 1100px) {{
      .hero, .section-grid, .metric-grid, .subgrid, .artifact-grid, .mapping-head, .mapping-row {{
        grid-template-columns: 1fr;
      }}
      .topbar {{
        flex-direction: column;
        align-items: flex-start;
      }}
      .status-row {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
        <div class="brand">
          <div class="logo"></div>
          <div>
          <h1>Verification Automation Platform</h1>
          <p>Repo-aware HLT / LLT verification with review, execution, coverage, and proof.</p>
          </div>
        </div>
          <div class="status-row">
        <span class="chip {'green' if config.poolside_base_url and config.poolside_api_key else 'amber'}">Poolside {html.escape(poolside_badge)}</span>
        <span class="chip">Repo root: {html.escape(str(config.repo_root))}</span>
        <span class="chip">{html.escape(auto_badge)}</span>
      </div>
    </div>

    <div class="hero">
      <section class="panel form">
        <form method="post" action="/run">
          <div class="field">
            <label>Requirement ID / Name</label>
            <input name="requirement" value="{requirement}" placeholder="Requirement ID or name" />
          </div>
          <div class="field">
            <label>Verification Mode</label>
            <select name="mode">
              <option value="Auto" {"selected" if selected_mode.lower() == "auto" else ""}>Auto detect</option>
              <option value="Direct" {"selected" if selected_mode.lower() == "direct" else ""}>Direct</option>
              <option value="Hybrid" {"selected" if selected_mode.lower() == "hybrid" else ""}>Hybrid</option>
              <option value="Manual" {"selected" if selected_mode.lower() == "manual" else ""}>Manual</option>
            </select>
          </div>
          <div class="field">
            <label>Requirement Text</label>
            <textarea name="text" placeholder="Paste the requirement text here.">{text}</textarea>
          </div>
          <div class="field">
            <label>Source Snippet</label>
            <textarea name="snippet" placeholder="Optional source snippet or signature.">{snippet}</textarea>
          </div>
          <div class="field">
            <label>Repo Root</label>
            <input name="repo_root" value="{repo_root}" />
          </div>
          <div class="field">
            <label>Output Directory</label>
            <input name="output_dir" value="{output_dir}" />
          </div>
          <div class="checkbox-row">
            <label class="check"><input type="checkbox" name="use_graph" {graph_checked} /> Use LangGraph when available</label>
            <label class="check"><input type="checkbox" name="require_review" {review_checked} /> Require review gate</label>
          </div>
          <div class="button-row">
            <button class="button primary" type="submit">Run Verification</button>
            <a class="button secondary" href="/api/state" target="_blank" rel="noreferrer">View JSON State</a>
          </div>
        </form>
      </section>

      <section class="stack">
        {result_section}

          <section class="panel panel-soft">
            <div class="panel-heading">
            <h2>Draft Artifacts</h2>
            <span class="chip">{len(artifacts) or 0} files</span>
          </div>
          <div class="artifact-grid">
            {artifact_html}
          </div>
        </section>
      </section>
    </div>

    <div class="section-grid">
      <section class="panel panel-soft">
        <div class="panel-heading">
          <h2>Agent Timeline</h2>
          <span class="chip {'amber' if busy or last_result.get('status') == 'blocked' else 'green' if last_result else 'muted'}">{html.escape(status_label)}</span>
        </div>
        <div class="timeline">
          {step_html}
        </div>
      </section>

        <section class="panel panel-soft">
          <div class="panel-heading">
            <h2>Coverage Summary</h2>
            <span class="chip">{len(coverage) or 0} items</span>
          </div>
        <div class="timeline">
          {coverage_lines}
        </div>
      </section>

      <section class="panel panel-soft">
        <div class="panel-heading">
          <h2>Logs & Evidence</h2>
          <span class="chip">{'live' if busy else 'latest run'}</span>
        </div>
        <div class="logs">
          {log_lines}
        </div>
      </section>

      <section class="panel panel-soft">
        <div class="panel-heading">
          <h2>Traceability Mapping</h2>
          <span class="chip">{len(mapping_rows) or 0} rows</span>
        </div>
        <div class="mapping-table">
          {mapping_html}
        </div>
      </section>
    </div>

    <div class="footer">
      Launch once from the CLI or Docker, then review the generated artifacts, evidence, and coverage in one place.
    </div>
  </div>
</body>
</html>
"""

    def _serve_download(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        artifact = params.get("artifact", [""])[0]
        if not artifact:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        path = self._artifact_path(artifact)
        if path is None or not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _artifact_path(self, artifact: str) -> Path | None:
        last_result = self._state_snapshot()["last_result"]
        artifacts = last_result.get("artifacts", {}) if isinstance(last_result, dict) else {}
        raw = artifacts.get(artifact)
        if raw:
            return Path(raw)
        if artifact in {"rapita/rvsconfig.xml", "rapita/rapita-node-mapping.md"}:
            path = self.runtime.default_output_dir / artifact
            return path
        return None

    def _state_snapshot(self) -> dict[str, Any]:
        with self.runtime.state.lock:
            return {
                "busy": self.runtime.state.busy,
                "has_run": self.runtime.state.has_run,
                "last_request": dict(self.runtime.state.last_request),
                "last_result": dict(self.runtime.state.last_result),
                "last_error": self.runtime.state.last_error,
                "started_at": self.runtime.state.started_at,
                "finished_at": self.runtime.state.finished_at,
            }

    def _send_html(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_plain(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_json(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _compute_status_label(self, last_result: dict[str, Any], busy: bool) -> str:
        if busy:
            return "Running"
        if not last_result:
            return "Idle"
        if last_result.get("status") == "blocked":
            return "Blocked"
        test_results = last_result.get("proof_report", {}).get("test_results", {})
        if isinstance(test_results, dict) and test_results.get("failed", 0) > 0:
            return "Needs Triage"
        if isinstance(test_results, dict) and test_results.get("passed"):
            return "Passed"
        if last_result.get("review_status") == "pending_review":
            return "Needs Review"
        if last_result.get("rapita", {}).get("summary") == "Rapita pipeline not executed on this machine.":
            return "Draft Evidence"
        return "Ready"

    def _render_resolution_summary(self, resolved_requirement: dict[str, Any]) -> str:
        if not isinstance(resolved_requirement, dict) or not resolved_requirement:
            return "<div class='empty-state'>Enter a real requirement ID to resolve from the repo.</div>"
        file_path = html.escape(str(resolved_requirement.get("file_path", "") or "unresolved"))
        notes = html.escape(str(resolved_requirement.get("notes", "") or "None"))
        bold_terms = resolved_requirement.get("bold_terms", []) or []
        matched_lines = resolved_requirement.get("matched_lines", []) or []
        excerpt = html.escape(str(resolved_requirement.get("excerpt", "") or ""))
        terms_html = "".join(f"<span class='chip'>{html.escape(str(term))}</span>" for term in bold_terms[:8]) or "<span class='muted'>No bold terms found.</span>"
        lines_html = "".join(f"<div class='log-line'>{html.escape(str(line))}</div>" for line in matched_lines[:4]) or "<div class='muted'>No matched lines.</div>"
        return (
            f"<div class='metric-grid' style='grid-template-columns:1fr; margin-bottom:12px;'>"
            f"<div class='metric'><span>File</span><strong>{file_path}</strong></div>"
            f"<div class='metric'><span>Notes</span><strong>{notes}</strong></div>"
            f"</div>"
            f"<div class='subpanel full' style='margin-top:0; padding:12px 0 0; border:none; background:transparent;'>"
            f"<h3>Bolded Terms</h3>"
            f"<div class='status-row' style='justify-content:flex-start; margin-top:8px;'>{terms_html}</div>"
            f"</div>"
            f"<div class='subpanel full' style='margin-top:12px; padding:12px 0 0; border:none; background:transparent;'>"
            f"<h3>Matched Lines</h3>"
            f"<div class='logs' style='max-height: 160px;'>{lines_html}</div>"
            f"</div>"
            f"<div class='subpanel full' style='margin-top:12px; padding:12px 0 0; border:none; background:transparent;'>"
            f"<h3>Excerpt</h3>"
            f"<p>{excerpt or 'No excerpt available.'}</p>"
            f"</div>"
        )

    def _render_mapping_rows(self, mappings: list[dict[str, Any]]) -> str:
        if not mappings:
            return "<div class='empty-state'>Resolved requirement mappings will appear here after a real repo match.</div>"
        rows = [
            "<div class='mapping-head'><span>Requirement Term</span><span>Source Term</span><span>Implementation</span><span>DD Entry</span></div>"
        ]
        for mapping in mappings:
            rows.append(
                "<div class='mapping-row'>"
                f"<span>{html.escape(str(mapping.get('requirement_term', '')))}</span>"
                f"<span>{html.escape(str(mapping.get('source_term', '')))}</span>"
                f"<span>{html.escape(str(mapping.get('implementation', '')))}</span>"
                f"<span>{html.escape(str(mapping.get('dd_entry', '')))}</span>"
                "</div>"
            )
        return "".join(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the verification automation web UI.")
    parser.add_argument("--repo-root", default=".", help="Repository root to scan.")
    parser.add_argument("--output-dir", default="artifacts-web", help="Directory for generated artifacts.")
    parser.add_argument("--requirement", default="", help="Default requirement ID or name.")
    parser.add_argument("--text", default="", help="Default requirement text.")
    parser.add_argument("--snippet", default="", help="Default source snippet.")
    parser.add_argument("--mode", default="Auto", choices=["Auto", "Direct", "Hybrid", "Manual"], help="Default verification mode.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local port for the UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for the UI.")
    parser.add_argument("--require-review", action="store_true", help="Require the review gate before execution.")
    parser.add_argument("--use-graph", action="store_true", help="Prefer LangGraph when available.")
    parser.add_argument("--auto-run", action="store_true", help="Auto-start a pipeline run on launch using the default inputs.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    return parser


def run_server(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).expanduser()
    config = AppConfig.load(repo_root)
    if args.require_review:
        config = replace(config, auto_approve=False)
    runtime = UIRuntime(
        config=config,
        default_requirement=args.requirement.strip(),
        default_text=args.text.strip(),
        default_snippet=args.snippet.strip(),
        default_output_dir=Path(args.output_dir).expanduser(),
        default_mode=args.mode,
        default_require_review=args.require_review,
        default_use_graph=args.use_graph,
        auto_run=args.auto_run,
    )

    handler = type("VerificationUIHandlerConfigured", (VerificationUIHandler,), {})
    handler.runtime = runtime
    httpd = ThreadingHTTPServer((args.host, args.port), handler)

    if args.auto_run and args.requirement.strip():
        payload = runtime.launch_payload(
            {
                "requirement": args.requirement,
                "text": args.text,
                "snippet": args.snippet,
                "repo_root": str(repo_root),
                "output_dir": str(Path(args.output_dir).expanduser()),
                "mode": args.mode,
                "require_review": "on" if args.require_review else "",
                "use_graph": "on" if args.use_graph else "",
            }
        )
        runtime.start_run(payload)

    url = f"http://{args.host}:{args.port}/"
    print(f"Verification UI listening on {url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - manual exit
        pass
    finally:
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_server(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
