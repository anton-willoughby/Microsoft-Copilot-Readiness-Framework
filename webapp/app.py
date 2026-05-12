"""
Microsoft Copilot Readiness Assessment — Flask web application.
Converts the PowerShell-based CopilotReadiness module to a cross-platform Python web app.
"""
import json
import queue
import threading
import uuid

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    Response,
    session,
    url_for,
)
from flask_session import Session

import config
from services import auth as auth_svc
from assessments import ca_policies, external_users, label_coverage, overshared_content, retention
from services.report_generator import generate as generate_report

app = Flask(__name__)
app.config.from_object(config)
Session(app)

# ── In-process state ──────────────────────────────────────────────────────────
# Keyed by session id; holds the device-flow dict while user authenticates.
_pending_flows: dict[str, dict] = {}
# Log queue for SSE streaming; one queue per session.
_log_queues: dict[str, queue.Queue] = {}
# Assessment running flag per session.
_running: dict[str, bool] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _session_id() -> str:
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


def _token() -> str | None:
    return session.get("access_token")


def _log_fn(sid: str):
    """Return a logging callable that feeds the SSE queue for this session."""
    def log(message: str):
        q = _log_queues.get(sid)
        if q:
            q.put(message)
    return log


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    sid = _session_id()
    # Pull any completed background results into the session
    if sid in _pending_results and not _running.get(sid):
        session["last_results"] = _pending_results.pop(sid)
        session.modified = True
    running = _running.get(sid, False) or bool(request.args.get("running"))
    results = session.get("last_results")
    device_flow = None
    flow_key = None

    # Expose pending device flow to the template
    fk = session.get("flow_key")
    if fk and fk in _pending_flows:
        flow_key = fk
        device_flow = _pending_flows[fk]

    return render_template(
        "index.html",
        running=running,
        results=results,
        device_flow=device_flow,
        flow_key=flow_key,
    )


@app.route("/signin", methods=["POST"])
def signin():
    tenant_url = request.form.get("tenantUrl", "").strip().rstrip("/")
    if not tenant_url:
        flash("Tenant URL is required.", "danger")
        return redirect(url_for("index"))

    import re
    if not re.match(r"^https://[a-z0-9-]+-admin\.sharepoint\.com$", tenant_url, re.IGNORECASE):
        flash("Tenant URL must be in the format https://&lt;tenant&gt;-admin.sharepoint.com", "danger")
        return redirect(url_for("index"))

    try:
        flow = auth_svc.start_device_flow()
    except Exception as exc:
        flash(f"Failed to start sign-in: {exc}", "danger")
        return redirect(url_for("index"))

    flow_key = str(uuid.uuid4())
    _pending_flows[flow_key] = flow
    session["flow_key"] = flow_key
    session["tenant_url"] = tenant_url
    return redirect(url_for("index"))


@app.route("/signin/complete", methods=["POST"])
def signin_complete():
    flow_key = request.form.get("flow_key") or session.get("flow_key")
    if not flow_key or flow_key not in _pending_flows:
        flash("Sign-in session expired. Please try again.", "warning")
        return redirect(url_for("index"))

    flow = _pending_flows.pop(flow_key, None)
    session.pop("flow_key", None)

    try:
        token_result = auth_svc.acquire_token_by_device_flow(flow)
    except Exception as exc:
        flash(f"Authentication failed: {exc}", "danger")
        return redirect(url_for("index"))

    session["access_token"] = token_result["access_token"]
    account = token_result.get("id_token_claims", {})
    session["connected_user"] = account.get("upn") or account.get("preferred_username") or account.get("name", "")
    session["connected"] = True

    # Resolve org display name
    try:
        from services.graph_client import graph_get
        org = graph_get(token_result["access_token"], f"{config.GRAPH_BASE}/organization?$select=displayName")
        value = org.get("value") or []
        session["org_name"] = value[0]["displayName"] if value else session.get("tenant_url", "")
    except Exception:
        session["org_name"] = session.get("tenant_url", "")

    flash(f"Connected as {session['connected_user']} to {session['org_name']}.", "success")
    return redirect(url_for("index"))


@app.route("/signout")
def signout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))


@app.route("/run", methods=["POST"])
def run_assessments():
    token = _token()
    if not token:
        flash("Please sign in first.", "warning")
        return redirect(url_for("index"))

    sid = _session_id()
    if _running.get(sid):
        flash("An assessment is already running.", "info")
        return redirect(url_for("index"))

    selected = request.form.getlist("assessments")
    if not selected:
        flash("Select at least one assessment.", "warning")
        return redirect(url_for("index"))

    include_od = bool(request.form.get("include_onedrive"))
    try:
        sample_size = int(request.form.get("sample_size", 100))
    except ValueError:
        sample_size = 100

    _log_queues[sid] = queue.Queue()
    _running[sid] = True
    # Store selections for the background thread
    session["running_assessments"] = selected
    session.modified = True

    def _run():
        log = _log_fn(sid)
        results = {}
        assessment_map = {
            "CAPolicies": lambda: ca_policies.run(token, log),
            "ExternalUserAccess": lambda: external_users.run(token, log),
            "LabelCoverage": lambda: label_coverage.run(token, log, include_onedrive=include_od, sample_size=sample_size),
            "OversharedContent": lambda: overshared_content.run(token, log, include_onedrive=include_od, sample_size=sample_size),
            "RetentionLabels": lambda: retention.run(token, log),
        }
        for name in selected:
            if name in assessment_map:
                log(f"[Info] Starting assessment: {name}")
                try:
                    results[name] = assessment_map[name]()
                    log(f"[Success] Completed: {name}")
                except Exception as exc:
                    log(f"[Error] Assessment {name} failed: {exc}")
                    results[name] = {
                        "Name": name,
                        "ReadinessScore": 0,
                        "ReadinessRating": "Not Ready",
                        "Summary": {"Error": str(exc)},
                        "Findings": [],
                    }

        with app.app_context():
            pass  # results stored below via queue sentinel

        q = _log_queues.get(sid)
        if q:
            q.put(None)  # sentinel to signal done

        # We can't write to flask session from a thread without request context.
        # Store results in a thread-safe sidecar dict keyed by sid.
        _pending_results[sid] = results
        _running[sid] = False

    threading.Thread(target=_run, daemon=True).start()
    return redirect(url_for("index") + "?running=1")


# Sidecar for results from background threads
_pending_results: dict[str, dict] = {}


@app.route("/log-stream")
def log_stream():
    sid = _session_id()
    q = _log_queues.get(sid)

    def generate():
        if not q:
            yield "event: done\ndata: \n\n"
            return
        while True:
            try:
                item = q.get(timeout=30)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                # Assessment complete — transfer results to session
                if sid in _pending_results:
                    session["last_results"] = _pending_results.pop(sid)
                    session.modified = True
                yield "event: done\ndata: complete\n\n"
                return
            # Colour-code by log level prefix
            yield f"event: log\ndata: {item}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/report")
def report():
    results = session.get("last_results")
    if not results:
        flash("Run at least one assessment first.", "warning")
        return redirect(url_for("index"))
    tenant_url = session.get("tenant_url", "")
    html = generate_report(results, tenant_url)
    return Response(html, mimetype="text/html")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
