"""HTML report generator — port of New-CRReadinessReport.ps1"""
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

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
