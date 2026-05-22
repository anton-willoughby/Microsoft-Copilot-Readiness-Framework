# Microsoft Copilot for M365 Readiness Assessment Framework

## Quick Start

**Version:** 1.0  
**Created by:** Nitron Digital LLC  
**Date:** December 2025

This repository contains a Python/Flask web application for assessing Microsoft 365 tenant readiness for Microsoft 365 Copilot adoption. The legacy implementation has been retired; the active application lives in `webapp/`.

## Run The App

Create and activate a virtual environment:

```text
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```text
pip install -r webapp/requirements.txt
```

Start the Flask app:

```text
python webapp/app.py
```

Open the application:

```text
http://127.0.0.1:5000
```

## Application Flow

1. Open the splash page.
2. Select **Sign in to begin assessment**.
3. Complete Microsoft interactive sign-in.
4. Enter the client's SharePoint Admin URL, for example `https://contoso-admin.sharepoint.com`.
5. Select the assessments to run.
6. Select **Run Selected** or **Run All**.
7. Review results in the dashboard or download the consolidated HTML report.

The run buttons remain disabled until a valid SharePoint Admin URL is entered.

## Authentication

The app uses MSAL for Python with the well-known Microsoft Graph Command Line Tools public client. This keeps the consultant workflow simple: client tenants do not need to create a custom app registration just to run the assessment.

The user signs in interactively and consents to delegated Microsoft Graph permissions needed by the selected assessments. Some permissions may require administrator consent in the client tenant.

## Required Microsoft Graph Permissions

The app requests delegated scopes for the active assessment set:

- `Policy.Read.All` for Conditional Access policy assessment
- `Directory.Read.All` for directory and organization metadata
- `User.Read.All` for external user inventory
- `AuditLog.Read.All` for sign-in activity
- `Sites.Read.All` for SharePoint site discovery
- `Files.Read.All` for SharePoint and OneDrive file metadata and permissions

## Assessments

### Conditional Access Policies

Reviews Conditional Access policies for Copilot compatibility, including MFA enforcement, device requirements, blocking risks, and session control settings.

### External User Access

Audits guest users and detected SharePoint/OneDrive access patterns, including inactive users, consumer email domains, and elevated permissions.

### Sensitivity Label Coverage

Samples SharePoint and optional OneDrive content to calculate how much discovered content has sensitivity labels applied.

### Overshared Content

Scans SharePoint and optional OneDrive content permissions for anonymous links, broad sharing, and high-risk group access.

### Retention Labels And Policies

Uses Microsoft Graph endpoints to evaluate retention label and policy readiness without requiring Security & Compliance command modules.

## Outputs

- In-browser readiness dashboard
- Per-assessment readiness scores and ratings
- Live assessment log output while scans run
- Downloadable consolidated `CopilotReadinessReport_[timestamp].html`

## Scoring

Read [Scoring-Methodology.md](Scoring-Methodology.md) for the scoring model and readiness rating thresholds.

## Repository Layout

```text
webapp/
  app.py                  Flask application entry point
  config.py               Graph, Flask, and scan configuration
  requirements.txt        Python dependencies
  assessments/            Assessment modules
  services/               Auth, Graph client, and report generation
  templates/              Flask/Jinja templates
Scoring-Methodology.md    Scoring model documentation
LICENSE                   License terms
```

## Troubleshooting

If sign-in fails, confirm the user has permission to consent to the requested delegated Microsoft Graph scopes or ask a tenant administrator to grant consent.

If assessments return incomplete data, confirm the signed-in account has appropriate Microsoft 365 administrative roles and Graph permissions. At minimum, Global Reader plus workload-specific admin roles are recommended for complete tenant visibility.

If the app fails to start, confirm the virtual environment is active and dependencies were installed from `webapp/requirements.txt`.

## Support & Updates

**Created by:**  
Brandon Marcus  
Managing Principal, Nitron Digital LLC  
brandon@nitron.digital | (833) 3-NITRON

This is a living framework. As Microsoft releases new Copilot features and guidance, update the methodology and assessment logic accordingly. Check Microsoft's official documentation quarterly.

## License & Usage

This framework and associated software are licensed under the MIT License with Attribution. Copyright (c) 2025 Nitron Digital LLC.

This software is provided subject to the following conditions:

1. **Attribution Requirement:** All use of this software, whether in source or binary form, must include proper attribution to Nitron Digital LLC.
2. **Commercial Use Requirement:** Any commercial use of this software, including use in commercial products, services, or for-profit activities, must explicitly reference Nitron Digital LLC.

You may use these tools for client assessments, customize the application for specific client needs, brand deliverables with your company information, reference the framework in proposals and marketing, and modify or distribute the software with proper attribution.

You may not resell the framework itself as a product without attribution, share the software publicly without proper attribution to Nitron Digital LLC, claim authorship of the methodology, or use it commercially without explicit reference to Nitron Digital LLC.

For the complete license text, see [LICENSE](LICENSE).