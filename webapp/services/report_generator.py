"""HTML report generator for Copilot readiness assessment results."""
from html import escape
from datetime import datetime


BADGE_CLASS = {
    "Ready": "bg-success",
    "Nearly Ready": "bg-info text-dark",
    "Requires Work": "bg-warning text-dark",
    "Not Ready": "bg-danger",
}

DIMENSIONS = [
    ("CAPolicies", "Conditional Access"),
    ("ExternalUserAccess", "External User Access"),
    ("LabelCoverage", "Sensitivity Labels"),
    ("OversharedContent", "Overshared Content"),
    ("RetentionLabels", "Retention Labels"),
    ("M365Licensing", "M365 Licensing"),
    ("DefenderPosture", "Defender Posture"),
]


def _readiness_rating(score: float) -> str:
    if score >= 80:
        return "Ready"
    if score >= 60:
        return "Nearly Ready"
    if score >= 40:
        return "Requires Work"
    return "Not Ready"


def _rows(items: list, columns: list[str]) -> str:
    if not items:
        return f"<tr><td colspan='{len(columns)}' class='text-center text-muted'>No findings.</td></tr>"
    rows = []
    for item in items:
        cells = "".join(f"<td>{escape(str(item.get(c, '')))}</td>" for c in columns)
        rows.append(f"<tr>{cells}</tr>")
    return "".join(rows)


def _score_card(name: str, score: float, rating: str) -> str:
    badge = BADGE_CLASS.get(rating, "bg-secondary")
    return (
        f"<div class='col'>"
        f"<div class='card h-100 shadow-sm'>"
        f"<div class='card-body text-center'>"
        f"<h6 class='card-title fw-semibold'>{escape(name)}</h6>"
        f"<p class='display-6 fw-bold mb-1'>{score}</p>"
        f"<small class='text-muted'>/ 100</small><br>"
        f"<span class='badge {badge} mt-2'>{escape(rating)}</span>"
        f"</div></div></div>"
    )


PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
PRIORITY_BADGE = {"High": "bg-danger", "Medium": "bg-warning text-dark", "Low": "bg-secondary"}
STATUS_BADGE = {
    "Compliant": "bg-success",
    "Warning": "bg-warning text-dark",
    "Not Configured": "bg-danger",
}


def _priority_badge(p: str) -> str:
    cls = PRIORITY_BADGE.get(p, "bg-secondary")
    return f"<span class='badge {cls}'>{escape(p)}</span>"


def _status_badge(s: str) -> str:
    cls = STATUS_BADGE.get(s, "bg-secondary")
    return f"<span class='badge {cls}'>{escape(s)}</span>"


def _recommendations_html(all_recs: list) -> str:
    if not all_recs:
        return "<p class='text-muted'>No recommendations generated — all assessed areas appear compliant.</p>"
    sorted_recs = sorted(all_recs, key=lambda r: PRIORITY_ORDER.get(r.get("Priority", "Low"), 2))
    rows = []
    for r in sorted_recs:
        rows.append(
            f"<tr>"
            f"<td>{_priority_badge(r.get('Priority',''))}</td>"
            f"<td>{_status_badge(r.get('Status',''))}</td>"
            f"<td><small>{escape(r.get('Area',''))}</small></td>"
            f"<td>{escape(r.get('Observation',''))}</td>"
            f"<td>{escape(r.get('Recommendation',''))}</td>"
            f"</tr>"
        )
    return "".join(rows)


def generate(results: dict, tenant_url: str) -> str:
    scores = []
    radar_labels = []
    radar_data = []
    cards_html = []

    for key, display_name in DIMENSIONS:
        r = results.get(key)
        score = round(float(r["ReadinessScore"]), 2) if r and r.get("ReadinessScore") is not None else 0
        rating = r["ReadinessRating"] if r else "Not Ready"
        scores.append(score)
        radar_labels.append(display_name)
        radar_data.append(score)
        cards_html.append(_score_card(display_name, score, rating))

    overall_score = round(sum(scores) / len(scores), 2) if scores else 0
    overall_rating = _readiness_rating(overall_score)
    overall_badge = BADGE_CLASS.get(overall_rating, "bg-secondary")

    # CA findings
    ca = results.get("CAPolicies")
    ca_rows = []
    if ca and ca.get("Findings"):
        ca_rows = sorted(
            [f for f in ca["Findings"] if f.get("CopilotCompatibilityScore", 100) < 80],
            key=lambda x: x.get("CopilotCompatibilityScore", 0),
        )[:15]

    # External user rows
    ext = results.get("ExternalUserAccess")
    ext_rows = []
    if ext:
        high_risk = ext.get("HighRiskAccess") or [
            f for f in (ext.get("Findings") or []) if f.get("RiskLevel") in ("Critical", "High")
        ]
        ext_rows = high_risk[:15]

    # Label rows
    lbl = results.get("LabelCoverage")
    lbl_rows = (lbl.get("UnlabeledSensitive") or [])[:15] if lbl else []

    # Overshared rows
    osh = results.get("OversharedContent")
    osh_rows = (osh.get("Findings") or [])[:15] if osh else []

    # Retention rows
    ret = results.get("RetentionLabels")
    ret_rows = (ret.get("Findings") or [])[:15] if ret else []
    ret_label_rows = (ret.get("LabelInventory") or [])[:50] if ret else []

    # Label distribution chart
    ld = (lbl.get("LabelDistribution") or []) if lbl else []
    label_names_js = str([d["LabelName"] for d in ld] or ["No Data"]).replace("'", '"')
    label_vals_js = str([d["DocumentCount"] for d in ld] or [1]).replace("'", '"')
    radar_labels_js = str(radar_labels).replace("'", '"')
    radar_data_js = str(radar_data)

    # M365 Licensing
    lic = results.get("M365Licensing")
    lic_summary = (lic.get("Summary") or {}) if lic else {}
    lic_rows = (lic.get("Findings") or [])[:50] if lic else []

    # Defender Posture
    dfn = results.get("DefenderPosture")
    dfn_summary = (dfn.get("Summary") or {}) if dfn else {}
    dfn_risky_users = (dfn.get("RiskyUsers") or [])[:25] if dfn else []
    dfn_oauth_risks = (dfn.get("OAuthRisks") or [])[:25] if dfn else []
    dfn_mfa = (dfn.get("MFACoverage") or {}) if dfn else {}

    # SharePoint Permissions
    sp_perms = results.get("SharePointPermissions")
    sp_sites = (sp_perms.get("sites") or []) if sp_perms else []

    # Aggregate recommendations from all assessments that produce them
    all_recommendations: list = []
    for key in ("M365Licensing", "DefenderPosture", "CAPolicies"):
        r = results.get(key)
        if r and isinstance(r.get("Recommendations"), list):
            all_recommendations.extend(r["Recommendations"])
    recommendations_html = _recommendations_html(all_recommendations)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- Pre-compute complex HTML sections (avoid nested f-strings) ----

    # M365 Licensing section
    if lic:
        lic_available = lic_summary.get("CopilotLicensesAvailable", 0) or 0
        try:
            avail_int = int(lic_available)
        except (TypeError, ValueError):
            avail_int = 0
        avail_cls = "text-warning" if avail_int < 0 else "text-secondary"
        lic_section = (
            '<h2 class="section-header">M365 Copilot Licensing</h2>'
            '<div class="row g-3 mb-3">'
            '<div class="col-sm-4"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold text-primary">' + escape(str(lic_summary.get("CopilotLicensesPurchased", "N/A"))) + '</div>'
            '<small class="text-muted">Copilot Licenses Purchased</small></div></div>'
            '<div class="col-sm-4"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold text-success">' + escape(str(lic_summary.get("CopilotLicensesConsumed", "N/A"))) + '</div>'
            '<small class="text-muted">Assigned to Users</small></div></div>'
            '<div class="col-sm-4"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold ' + avail_cls + '">' + escape(str(lic_available)) + '</div>'
            '<small class="text-muted">Available / Unassigned</small></div></div>'
            '</div>'
            '<div class="table-responsive mb-4"><table class="table table-sm table-striped table-hover">'
            '<thead class="table-dark"><tr>'
            '<th>SKU</th><th>Purchased</th><th>Consumed</th><th>Available</th><th>Status</th><th>Copilot Service Plans</th>'
            '</tr></thead><tbody>' +
            _rows(lic_rows, ["SkuPartNumber", "Purchased", "Consumed", "Available", "Status", "CopilotServicePlans"]) +
            '</tbody></table></div>'
        )
    else:
        lic_section = '<p class="text-muted">M365 Licensing assessment was not run.</p>'

    # Defender section
    if dfn:
        risky_count = dfn_summary.get("RiskyUsersHighMedium", 0) or 0
        try:
            risky_int = int(risky_count)
        except (TypeError, ValueError):
            risky_int = 0
        risky_cls = "text-danger" if risky_int > 0 else "text-success"
        oauth_count = dfn_summary.get("OAuthAppsWithBroadPermissions", 0) or 0
        try:
            oauth_int = int(oauth_count)
        except (TypeError, ValueError):
            oauth_int = 0
        oauth_cls = "text-warning" if oauth_int > 0 else "text-success"

        risky_table = (
            '<h5 class="mt-3">Risky Users</h5>'
            '<div class="table-responsive mb-3"><table class="table table-sm table-striped table-hover">'
            '<thead class="table-dark"><tr><th>Display Name</th><th>UPN</th><th>Risk Level</th><th>Risk State</th><th>Last Updated</th></tr></thead>'
            '<tbody>' + _rows(dfn_risky_users, ["DisplayName", "UPN", "RiskLevel", "RiskState", "LastUpdated"]) + '</tbody></table></div>'
        ) if dfn_risky_users else '<p class="text-success small">No risky users detected.</p>'

        oauth_table = (
            '<h5 class="mt-3">OAuth Apps with Broad Permissions</h5>'
            '<div class="table-responsive mb-4"><table class="table table-sm table-striped table-hover">'
            '<thead class="table-dark"><tr><th>App Name</th><th>App ID</th><th>Publisher</th><th>Risky Permissions</th></tr></thead>'
            '<tbody>' + _rows(dfn_oauth_risks, ["AppName", "AppId", "Publisher", "RiskyPermissions"]) + '</tbody></table></div>'
        ) if dfn_oauth_risks else '<p class="text-success small">No OAuth apps with overly broad permissions detected.</p>'

        dfn_section = (
            '<h2 class="section-header">Defender Security Posture</h2>'
            '<div class="row g-3 mb-3">'
            '<div class="col-sm-3"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold text-primary">' + escape(str(dfn_summary.get("SecureScorePercent", "N/A"))) + '%</div>'
            '<small class="text-muted">Secure Score</small></div></div>'
            '<div class="col-sm-3"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold ' + risky_cls + '">' + escape(str(risky_count)) + '</div>'
            '<small class="text-muted">Risky Users (High/Med)</small></div></div>'
            '<div class="col-sm-3"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold text-secondary">' + escape(str(dfn_mfa.get("MFACoveragePercent", "N/A"))) + '%</div>'
            '<small class="text-muted">MFA Registration</small></div></div>'
            '<div class="col-sm-3"><div class="card text-center shadow-sm p-3">'
            '<div class="display-6 fw-bold ' + oauth_cls + '">' + escape(str(oauth_count)) + '</div>'
            '<small class="text-muted">OAuth App Risks</small></div></div>'
            '</div>' +
            risky_table +
            oauth_table
        )
    else:
        dfn_section = '<p class="text-muted">Defender Posture assessment was not run.</p>'

    # SharePoint Permissions section
    if sp_sites:
        site_cards = []
        for site in sp_sites:
            perm_rows = "".join(
                "<tr><td>" + escape(str(p.get("user", ""))) + "</td><td>" + escape(", ".join(p.get("roles", []))) + "</td></tr>"
                for p in site.get("permissions", [])
            ) or "<tr><td colspan='2' class='text-muted'>No explicit permissions found.</td></tr>"

            lib_html = ""
            for lib in site.get("libraries", []):
                lib_perm_rows = "".join(
                    "<tr><td>" + escape(str(p.get("user", ""))) + "</td><td>" + escape(", ".join(p.get("roles", []))) + "</td></tr>"
                    for p in lib.get("permissions", [])
                ) or "<tr><td colspan='2' class='text-muted small'>Inherits site permissions.</td></tr>"
                lib_html += (
                    '<div class="ms-2 mb-2"><strong class="small">' + escape(lib.get("name", "")) + '</strong>'
                    '<div class="table-responsive"><table class="table table-sm mb-0">'
                    '<thead class="table-light"><tr><th>User / Group</th><th>Roles</th></tr></thead>'
                    '<tbody>' + lib_perm_rows + '</tbody></table></div></div>'
                )

            site_cards.append(
                '<div class="card mb-3 shadow-sm">'
                '<div class="card-header fw-semibold">' + escape(site.get("name", "")) +
                ' &mdash; <a href="' + escape(site.get("url", "")) + '" target="_blank" class="text-decoration-none small">' +
                escape(site.get("url", "")) + '</a></div>'
                '<div class="card-body p-2">'
                '<h6 class="mb-1">Site Permissions</h6>'
                '<div class="table-responsive mb-2"><table class="table table-sm mb-0">'
                '<thead class="table-light"><tr><th>User / Group</th><th>Roles</th></tr></thead>'
                '<tbody>' + perm_rows + '</tbody></table></div>' +
                ('<h6 class="mt-2 mb-1">Document Libraries</h6>' + lib_html if lib_html else '<p class="text-muted small ms-2">No document libraries found.</p>') +
                '</div></div>'
            )
        sp_section = '<h2 class="section-header">SharePoint Permissions</h2>' + "".join(site_cards)
    elif sp_perms is not None:
        sp_section = '<h2 class="section-header">SharePoint Permissions</h2><p class="text-muted">No sites returned.</p>'
    else:
        sp_section = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Microsoft Copilot Readiness Assessment Report</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    body {{ font-family: 'Segoe UI', sans-serif; background:#f8f9fa; }}
    .hero {{ background: linear-gradient(135deg,#0078d4,#004e92); color:#fff; padding:2.5rem 2rem; }}
    .section-header {{ border-left:4px solid #0078d4; padding-left:.75rem; margin:2rem 0 1rem; }}
    table {{ font-size:.85rem; }}
  </style>
</head>
<body>
<div class="hero mb-4">
  <div class="container">
    <h1 class="fw-bold">Microsoft Copilot Readiness Assessment</h1>
    <p class="mb-1 opacity-75">Tenant: {escape(tenant_url)}</p>
    <p class="mb-0 opacity-75">Generated: {generated}</p>
    <div class="mt-3">
      <span class="display-5 fw-bold me-2">{overall_score}</span>
      <span class="text-white opacity-75">/ 100 Overall</span>
      <span class="badge {overall_badge} ms-2 fs-6">{escape(overall_rating)}</span>
    </div>
  </div>
</div>

<div class="container mb-5">

  <!-- Score cards -->
  <h2 class="section-header">Assessment Scores</h2>
  <div class="row row-cols-1 row-cols-md-3 row-cols-lg-5 g-3 mb-4">
    {"".join(cards_html)}
  </div>

  <!-- Charts -->
  <div class="row g-4 mb-4">
    <div class="col-md-6">
      <div class="card shadow-sm p-3">
        <h6 class="fw-semibold mb-3">Readiness Radar</h6>
        <canvas id="radarChart" height="200"></canvas>
      </div>
    </div>
    <div class="col-md-6">
      <div class="card shadow-sm p-3">
        <h6 class="fw-semibold mb-3">Sensitivity Label Distribution</h6>
        <canvas id="labelChart" height="200"></canvas>
      </div>
    </div>
  </div>

  <!-- Conditional Access -->
  <h2 class="section-header">Conditional Access — Compatibility Issues</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>Policy Name</th><th>Compatibility Score</th><th>Issues</th>
      </tr></thead>
      <tbody>{_rows(ca_rows, ["PolicyName","CopilotCompatibilityScore","CompatibilityIssues"])}</tbody>
    </table>
  </div>

  <!-- External Users -->
  <h2 class="section-header">External User Access — High Risk</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>User Email</th><th>Site URL</th><th>Permissions</th><th>Risk Level</th>
      </tr></thead>
      <tbody>{_rows(ext_rows, ["ExternalUserEmail","SiteUrl","Permissions","RiskLevel"])}</tbody>
    </table>
  </div>

  <!-- Sensitivity Labels -->
  <h2 class="section-header">Unlabeled Sensitive Content</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>File Name</th><th>Site URL</th><th>Sensitive Indicators</th>
      </tr></thead>
      <tbody>{_rows(lbl_rows, ["FileName","SiteUrl","SensitiveIndicators"])}</tbody>
    </table>
  </div>

  <!-- Overshared Content -->
  <h2 class="section-header">Overshared Content</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>Item Name</th><th>Site URL</th><th>Shared With</th><th>Risk Level</th><th>Reason</th>
      </tr></thead>
      <tbody>{_rows(osh_rows, ["ItemName","SiteUrl","SharedWith","RiskLevel","RiskReason"])}</tbody>
    </table>
  </div>

  <!-- Retention Policies -->
  <h2 class="section-header">Retention Policies</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>Policy Name</th><th>Status</th><th>Workloads</th><th>Action</th><th>Duration</th>
      </tr></thead>
      <tbody>{_rows(ret_rows, ["PolicyName","EnabledStatus","WorkloadsCovered","RetentionAction","RetentionDuration"])}</tbody>
    </table>
  </div>

  <!-- Retention Labels -->
  <h2 class="section-header">Retention Label Inventory</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>Label Name</th><th>Retention Action</th><th>Duration</th><th>Is Record Label</th>
      </tr></thead>
      <tbody>{_rows(ret_label_rows, ["LabelName","RetentionAction","RetentionDuration","IsRecordLabel"])}</tbody>
    </table>
  </div>

  <!-- M365 Licensing -->
  {lic_section}

  <!-- Defender Security Posture -->
  {dfn_section}

  <!-- SharePoint Permissions -->
  {sp_section}

  <!-- Prioritised Recommendations -->
  <h2 class="section-header">Prioritised Recommendations</h2>
  <div class="table-responsive mb-4">
    <table class="table table-sm table-striped table-hover">
      <thead class="table-dark"><tr>
        <th>Priority</th><th>Status</th><th>Area</th><th>Observation</th><th>Recommendation</th>
      </tr></thead>
      <tbody>{recommendations_html}</tbody>
    </table>
  </div>

</div><!-- /container -->

<script>
new Chart(document.getElementById('radarChart'), {{
  type: 'radar',
  data: {{
    labels: {radar_labels_js},
    datasets: [{{
      label: 'Readiness Score',
      data: {radar_data_js},
      backgroundColor: 'rgba(0,120,212,0.2)',
      borderColor: '#0078d4',
      pointBackgroundColor: '#0078d4'
    }}]
  }},
  options: {{ scales: {{ r: {{ min: 0, max: 100 }} }}, plugins: {{ legend: {{ display: false }} }} }}
}});
new Chart(document.getElementById('labelChart'), {{
  type: 'doughnut',
  data: {{
    labels: {label_names_js},
    datasets: [{{ data: {label_vals_js}, backgroundColor: ['#0078d4','#50e6ff','#2d7d9a','#004e92','#00b4d8','#90e0ef'] }}]
  }},
  options: {{ plugins: {{ legend: {{ position: 'right' }} }} }}
}});
</script>
</body>
</html>"""
