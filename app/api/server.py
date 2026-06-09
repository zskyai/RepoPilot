from __future__ import annotations

from pathlib import Path

from app.core.workflow import EnterpriseAgentWorkflow
from app.core.run_store import RunStore
from app.scenarios.repo_pilot import RepoPilotWorkflow
from app.scenarios.repo_pilot_graph import RepoPilotGraphWorkflow

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    FastAPI = None
    HTMLResponse = None
    BaseModel = object


ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "data" / "knowledge_base"


class ResearchRequest(BaseModel):
    query: str
    user_type: str = "enterprise_user"


class RepoPilotRequest(BaseModel):
    repo: str = "."
    issue: str
    run_tests: bool = False
    use_llm: bool = False
    require_llm: bool = False
    graph: bool = False
    apply_sandbox: bool = False
    apply_worktree: bool = False
    create_pr: bool = False
    poll_ci: bool = False
    ci_feedback: bool = False
    use_memory: bool = True
    save_memory: bool = True
    pr_number: int | None = None
    comment_body: str = ""
    require_approval: bool = True
    save_run: bool = False


if FastAPI:
    app = FastAPI(title="Enterprise Agent Platform", version="0.1.0")
    workflow = EnterpriseAgentWorkflow(KB_DIR)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/repo-pilot/ui", response_class=HTMLResponse)
    def repo_pilot_ui() -> str:
        return """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>RepoPilot Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f6f7fb; color: #111; }
    .wrap { max-width: 1100px; margin: 0 auto; }
    textarea, input { width: 100%; padding: 10px; margin: 8px 0 16px; box-sizing: border-box; }
    textarea { min-height: 120px; }
    button { padding: 10px 16px; background: #111827; color: white; border: none; cursor: pointer; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .panel { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
    pre { white-space: pre-wrap; word-break: break-word; background: #0b1020; color: #e5e7eb; padding: 12px; border-radius: 6px; overflow: auto; }
    .checks label { margin-right: 16px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>RepoPilot Dashboard</h1>
    <div class="panel">
      <label>Repository Path</label>
      <input id="repo" value="." />
      <label>Issue</label>
      <textarea id="issue">API 返回 JSON schema 字段不稳定，需要定位接口和模型定义</textarea>
      <div class="checks">
        <label><input type="checkbox" id="run_tests" checked /> run tests</label>
        <label><input type="checkbox" id="use_llm" checked /> use llm</label>
        <label><input type="checkbox" id="require_llm" checked /> require llm</label>
        <label><input type="checkbox" id="graph" checked /> graph</label>
        <label><input type="checkbox" id="apply_sandbox" checked /> apply sandbox</label>
        <label><input type="checkbox" id="apply_worktree" /> apply worktree</label>
        <label><input type="checkbox" id="create_pr" /> create pr</label>
        <label><input type="checkbox" id="poll_ci" /> poll ci</label>
        <label><input type="checkbox" id="ci_feedback" /> ci feedback</label>
        <label><input type="checkbox" id="use_memory" checked /> memory</label>
        <label><input type="checkbox" id="save_memory" checked /> save memory</label>
        <label><input type="checkbox" id="require_approval" checked /> approval gate</label>
        <label><input type="checkbox" id="save_run" checked /> save run</label>
      </div>
      <label>PR Number</label>
      <input id="pr_number" value="" />
      <label>Comment Body</label>
      <textarea id="comment_body"></textarea>
      <button onclick="runRepoPilot()">Run</button>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="panel"><h3>Summary</h3><pre id="summary"></pre></div>
      <div class="panel"><h3>Trace</h3><pre id="trace"></pre></div>
    </div>
    <div class="panel" style="margin-top:16px;"><h3>Full JSON</h3><pre id="json"></pre></div>
  </div>
  <script>
    async function runRepoPilot() {
      const payload = {
        repo: document.getElementById('repo').value,
        issue: document.getElementById('issue').value,
        run_tests: document.getElementById('run_tests').checked,
        use_llm: document.getElementById('use_llm').checked,
        require_llm: document.getElementById('require_llm').checked,
        graph: document.getElementById('graph').checked,
        apply_sandbox: document.getElementById('apply_sandbox').checked,
        apply_worktree: document.getElementById('apply_worktree').checked,
        create_pr: document.getElementById('create_pr').checked,
        poll_ci: document.getElementById('poll_ci').checked,
        ci_feedback: document.getElementById('ci_feedback').checked,
        use_memory: document.getElementById('use_memory').checked,
        save_memory: document.getElementById('save_memory').checked,
        pr_number: document.getElementById('pr_number').value ? Number(document.getElementById('pr_number').value) : null,
        comment_body: document.getElementById('comment_body').value,
        require_approval: document.getElementById('require_approval').checked,
        save_run: document.getElementById('save_run').checked
      };
      const res = await fetch('/repo-pilot/diagnose', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      const ev = data.evaluation || {};
      const scores = ev.scores || {};
      document.getElementById('summary').textContent = JSON.stringify({
        overall: ev.overall,
        passed: ev.passed,
        scores,
        saved_run_id: data.analysis?.saved_run_id,
        graph_architecture: data.analysis?.graph_architecture,
        repair_rounds: data.analysis?.repair_rounds,
        sandbox_repair_rounds: data.analysis?.sandbox_repair_rounds,
        worktree_apply: data.analysis?.worktree_runs,
        github: data.pr_plan?.github,
        memory_hits: data.analysis?.memory_hits,
        saved_memory_id: data.analysis?.saved_memory_id,
        approval_gate: data.analysis?.approval_gate,
        pr_ready: data.pr_plan?.ready
      }, null, 2);
      document.getElementById('trace').textContent = JSON.stringify(data.analysis?.graph_trace || data.trace || [], null, 2);
      document.getElementById('json').textContent = JSON.stringify(data, null, 2);
    }
  </script>
</body>
</html>"""

    @app.post("/research")
    def research(req: ResearchRequest) -> dict:
        task = workflow.run(req.query, req.user_type)
        return task.to_dict()

    @app.post("/repo-pilot/diagnose")
    def repo_pilot(req: RepoPilotRequest) -> dict:
        workflow_cls = RepoPilotGraphWorkflow if req.graph else RepoPilotWorkflow
        run_kwargs = dict(
            run_tests=req.run_tests,
            apply_sandbox=req.apply_sandbox,
            apply_worktree=req.apply_worktree,
            create_pr=req.create_pr,
            poll_ci=req.poll_ci,
            ci_feedback=req.ci_feedback,
            use_memory=req.use_memory,
            save_memory=req.save_memory,
            pr_number=req.pr_number,
            comment_body=req.comment_body,
        )
        if req.graph:
            run_kwargs["require_approval"] = req.require_approval
        result = workflow_cls(use_llm=req.use_llm, require_llm=req.require_llm).run(
            req.repo,
            req.issue,
            **run_kwargs,
        )
        payload = result.to_dict()
        if req.save_run:
            payload["analysis"]["saved_run_id"] = RunStore(Path(req.repo) / ".repopilot" / "runs.sqlite3").save(payload)
        return payload
else:
    app = None
