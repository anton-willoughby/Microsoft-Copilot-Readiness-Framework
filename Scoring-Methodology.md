# Copilot Readiness Assessment — Scoring Methodology

Each assessment produces a **ReadinessScore** between 0 and 100.  
The **Overall Score** shown on the report is the simple arithmetic average of all assessment scores that ran successfully.

---

## Readiness Ratings

The same thresholds apply to every assessment score and to the overall score.

| Score range | Rating |
|---|---|
| ≥ 80 | **Ready** |
| 60 – 79 | **Nearly Ready** |
| 40 – 59 | **Requires Work** |
| < 40 | **Not Ready** |

---

## 1. Conditional Access Policies

**Model:** penalty per policy, final score = average across all CA policies.

Each CA policy starts at **100** and penalties are deducted:

| Condition | Penalty |
|---|---|
| Policy blocks all apps and has no Copilot exclusion | −100 |
| Enabled, applies to All Users, and has no MFA requirement | −20 |
| Enabled, applies to All Users, and has no compliant-device requirement | −10 |
| Sign-in frequency enabled and set to fewer than 4 hours/days | −15 |

A single policy score cannot go below 0.

The **assessment score** is the average `CopilotCompatibilityScore` across all CA policies in the tenant (including disabled policies, which are scored but not penalised for missing controls).

**Readiness rating** uses a separate heuristic (not the numeric score thresholds):

| Condition | Rating |
|---|---|
| Zero compatibility issues AND at least one policy requires MFA | Ready |
| ≤ 2 compatibility issues | Nearly Ready |
| ≤ 5 compatibility issues | Requires Work |
| > 5 compatibility issues | Not Ready |

**Example:** A tenant with three CA policies scoring 100, 80, and 60 produces an assessment score of **80** (Ready).

---

## 2. External User Access

**Model:** penalty per *user*, starts at 100.

After all sites are scanned, each guest user receives a single `HighestRiskLevel` based on the worst access record found for that user:

### Per-access-record risk classification

| Condition | Effect |
|---|---|
| Role matches `owner` or `fullcontrol` | → **Critical**, records `Full Control` permission |
| Role matches `write`, `edit`, or `manage` | → **High**, records `Edit` permission |
| Anything else | → **Low**, records `Read` permission |
| Sign-in inactive ≥ 90 days | Elevates risk to at least **Medium** |
| Domain is gmail.com, yahoo.com, outlook.com, hotmail.com, or live.com | Elevates risk to at least **Medium** |

The scan uses either **drive-root permissions** (`Sites.Read.All` / `Files.Read.All`) or **full site permissions** (`Sites.FullControl.All`) depending on granted consent.

### Score formula

```
score = max(0,  100
              − (criticalRiskUsers × 20)
              − (highRiskUsers     × 10)
              − (fullControlUsers  × 15))
```

`criticalRiskUsers`, `highRiskUsers`, and `fullControlUsers` are counts of *distinct users* at each level.  
A user found on **zero** sites (i.e. exists in AAD but not detected in any site permission) carries no penalty.

**Example:** 1 guest user with Read-only access, no stale sign-in, non-consumer domain → no penalties → **100 / 100**.

**Readiness rating** uses a separate heuristic:

| Condition | Rating |
|---|---|
| 0 Critical users, 0 Full Control users, and < 10 % inactive | Ready |
| ≤ 2 Critical users AND ≤ 2 Full Control users | Nearly Ready |
| ≤ 5 Critical users | Requires Work |
| > 5 Critical users | Not Ready |

---

## 3. Sensitivity Label Coverage

**Model:** score = percentage of scanned documents that carry a sensitivity label.

```
score = round( (labeledDocuments / totalDocumentsScanned) × 100, 2 )
```

Documents with no label (`sensitivityLabel` absent or empty in the Graph response) count as unlabelled.  
If zero documents are found the score is **0**.

The score feeds directly into the standard rating thresholds:

| Score | Rating |
|---|---|
| ≥ 80 % | Ready |
| 60 – 79 % | Nearly Ready |
| 40 – 59 % | Requires Work |
| < 40 % | Not Ready |

**Example:** 446 documents scanned, 0 labelled → **0 / 100** (Not Ready).

> **Note:** Label names require a Security & Compliance session (`Connect-IPPSSession`). Without one, label GUIDs appear in the report but scoring is unaffected.

---

## 4. Overshared Content

**Model:** penalty per *finding* (a finding = one file/item at a specific site shared in a risky way), starts at 100.

### Risk classification per sharing instance

| Sharing target | Risk level |
|---|---|
| Group named `Everyone` (any variant) | **Critical** |
| Group named `Everyone except external users` | **High** |
| Security group with > 500 members | **Medium** |
| Named user or small group | **Low** (not recorded as a finding) |

### Score formula

```
score = max(0,  100
              − (criticalFindings × 20)
              − (highFindings     × 10)
              − (mediumFindings   ×  5))
```

Low-risk findings carry no penalty and are not counted.

**Example:** No Everyone/large-group sharing found → 0 penalties → **100 / 100** (Ready).

---

## 5. Retention Labels & Policies

**Model:** additive, starts at 0. Points are awarded for each workload covered by at least one *enabled* retention policy.

| Condition | Points |
|---|---|
| An enabled policy covers **SharePoint** | +25 |
| An enabled policy covers **OneDrive** | +20 |
| An enabled policy covers **Exchange** | +20 |
| An enabled policy covers **Teams** (Chat, Channel, or Teams location) | +15 |
| At least one enabled policy has a **delete or KeepAndDelete** action | +20 |

Maximum possible score: **100**.  
A workload only earns its points once regardless of how many policies cover it.

**Example:** SharePoint (+25) + Exchange (+20) + delete action present (+20) = **65 / 100** (Nearly Ready).

> The Python implementation uses Microsoft Graph retention endpoints and does not require Security & Compliance command modules.

---

## Overall Score

```
overallScore = round( average( score₁, score₂, … scoreₙ ), 2 )
```

Only assessments that completed without error contribute to the average. A failed assessment is excluded rather than counting as 0.

---

## Source references

| Assessment | Scoring logic location |
|---|---|
| Conditional Access | `webapp/assessments/ca_policies.py` |
| External User Access | `webapp/assessments/external_users.py` |
| Sensitivity Labels | `webapp/assessments/label_coverage.py` |
| Overshared Content | `webapp/assessments/overshared_content.py` |
| Retention Labels | `webapp/assessments/retention.py` |
| Rating thresholds | Assessment modules and `webapp/services/report_generator.py` |
| Overall average | `webapp/services/report_generator.py` |
