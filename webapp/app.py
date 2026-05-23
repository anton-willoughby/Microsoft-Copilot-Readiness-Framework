"""
Microsoft Copilot Readiness Assessment — Flask web application.
Runs Microsoft 365 Copilot readiness assessments through a local Python web app.
"""
import queue
import re
import threading
import uuid
from datetime import datetime

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
from assessments import ca_policies
from assessments import defender_posture
from assessments import external_users
from assessments import label_coverage
from assessments import m365_licensing
from assessments import overshared_content
from assessments import retention
from assessments import sharepoint_permissions
from services.report_generator import generate as generate_report

app = Flask(__name__)
app.config.from_object(config)
Session(app)

# ── In-process state ──────────────────────────────────────────────────────────
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


def _normalize_tenant_url(value: str) -> str | None:
    tenant_url = (value or "").strip().rstrip("/")
    if re.match(r"^https://[a-z0-9-]+-admin\.sharepoint\.com$", tenant_url, re.IGNORECASE):
        return tenant_url
    return None


def _pull_pending_results(sid: str):
    if sid in _pending_results and not _running.get(sid):
        session["last_results"] = _pending_results.pop(sid)
        session.modified = True


def _apply_token_result(token_result: dict):
    session["access_token"] = token_result["access_token"]
    account = token_result.get("id_token_claims", {})
    session["connected_user"] = account.get("upn") or account.get("preferred_username") or account.get("name", "")
    session["connected"] = True

    missing = auth_svc.check_missing_scopes(token_result)
    session["missing_scopes"] = missing  # empty list = all scopes granted

    try:
        from services.graph_client import graph_get
        org = graph_get(token_result["access_token"], f"{config.GRAPH_BASE}/organization?$select=displayName")
        value = org.get("value") or []
        session["org_name"] = value[0]["displayName"] if value else session.get("tenant_url", "")
    except Exception:
        session["org_name"] = session.get("tenant_url", "")


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    _session_id()
    if session.get("connected"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("connected"):
        flash("Sign in to begin an assessment.", "info")
        return redirect(url_for("index"))

    sid = _session_id()
    _pull_pending_results(sid)
    running = _running.get(sid, False) or bool(request.args.get("running"))
    results = session.get("last_results")

    return render_template(
        "dashboard.html",
        running=running,
        results=results,
        tenant_url=session.get("tenant_url", ""),
    )


@app.route("/signin")
def signin():
    if session.get("connected"):
        return redirect(url_for("dashboard"))

    try:
        token_result = auth_svc.acquire_token_interactive()
    except Exception as exc:
        flash(f"Authentication failed: {exc}", "danger")
        return redirect(url_for("index"))

    _apply_token_result(token_result)
    flash(f"Connected as {session['connected_user']} to {session['org_name']}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/signout")
def signout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))


@app.route("/reauth")
def reauth():
    """Force a fresh interactive login with consent prompt.

    Used when the stored token is missing required scopes — presents the
    Microsoft consent screen so the user can approve any new permissions.
    """
    try:
        token_result = auth_svc.reacquire_token_for_consent()
    except Exception as exc:
        flash(f"Re-authentication failed: {exc}", "danger")
        return redirect(url_for("dashboard"))

    _apply_token_result(token_result)
    missing = session.get("missing_scopes", [])
    if missing:
        flash(
            f"Re-authenticated, but the following permissions were still not granted: "
            f"{', '.join(missing)}. Some assessments may be limited.",
            "warning",
        )
    else:
        flash("Permissions refreshed successfully — all required scopes are now granted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/run", methods=["POST"])
def run_assessments():
    token = _token()
    if not token:
        flash("Please sign in first.", "warning")
        return redirect(url_for("index"))

    tenant_url = _normalize_tenant_url(request.form.get("tenantUrl", ""))
    if not tenant_url:
        flash("Enter a valid SharePoint Admin URL before running an assessment.", "warning")
        return redirect(url_for("dashboard"))

    session["tenant_url"] = tenant_url

    sid = _session_id()
    if _running.get(sid):
        flash("An assessment is already running.", "info")
        return redirect(url_for("dashboard"))

    selected = request.form.getlist("assessments")
    if not selected:
        flash("Select at least one assessment.", "warning")
        return redirect(url_for("dashboard"))

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
            "DefenderPosture": lambda: defender_posture.run(token, log),
            "ExternalUserAccess": lambda: external_users.run(token, log),
            "LabelCoverage": lambda: label_coverage.run(token, log, include_onedrive=include_od, sample_size=sample_size),
            "M365Licensing": lambda: m365_licensing.run(token, log),
            "OversharedContent": lambda: overshared_content.run(token, log, include_onedrive=include_od, sample_size=sample_size),
            "RetentionLabels": lambda: retention.run(token, log),
            "RetentionPolicies": lambda: retention.run(token, log),
            "SharePointPermissions": lambda: sharepoint_permissions.run(token, log),
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
    return redirect(url_for("dashboard") + "?running=1")


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
                # Assessment complete. Avoid mutating session during streaming response;
                # index() will transfer _pending_results into session safely.
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
        return redirect(url_for("dashboard" if session.get("connected") else "index"))
    tenant_url = session.get("tenant_url", "")
    html = generate_report(results, tenant_url)
    return Response(html, mimetype="text/html")


@app.route("/report/download")
def report_download():
    results = session.get("last_results")
    if not results:
        flash("Run at least one assessment first.", "warning")
        return redirect(url_for("dashboard" if session.get("connected") else "index"))

    tenant_url = session.get("tenant_url", "")
    html = generate_report(results, tenant_url)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"CopilotReadinessReport_{timestamp}.html"

    return Response(
        html,
        mimetype="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
