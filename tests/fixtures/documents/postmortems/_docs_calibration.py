"""Six further complete postmortems (fixtures 11-16), written for judge calibration.

Each one states a root cause, and each is built so that a plausible-sounding
wrong answer about it is available to a judge. R7.11 needs at least twenty
human-scored `root_cause` cases, and a calibration sample in which every
candidate is right measures nothing; these give the wrong candidates something
concrete to be wrong about.

  11  a job scheduled in wall-clock time that did not exist on the DST change
  12  no deployment happened - the cause is a flag service upgrade
  13  a DDoS was suspected, investigated and ruled out in the document itself
  14  latent, found in a DR exercise; no customer impact
  15  two causes, stated as jointly necessary
  16  written in German

Layouts differ from 01-10 and from each other: a plain design doc, a status
report with tiles, a security-team report, a DR exercise record, an issue
tracker export, and a German-language memo.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from _common import (
    AMBER, BODY, BODY_S, CAPTION, GREEN, GREY, H1, H2, INK, MONO_S, NAVY, OUT, P,
    RED, RULE, SERIF, SERIF_H, SMALL, STEEL, TEAL,
    ParagraphStyle, bar_chart, bullets, grid_table, kv_table, line_chart, panel,
    tiles,
)

TABLE_S = ParagraphStyle("cal_t", parent=BODY_S, fontSize=7.2, leading=9.2)


# ================================================== 11 - plain design doc =====

def doc_11():
    path = OUT / "INC-5502-settlement-export-skipped-dst.pdf"
    W = A4[0] - 50 * mm
    H = ParagraphStyle("h11", parent=H2, textColor=TEAL, fontSize=11)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(25 * mm, 12 * mm,
                          "Northwind Payments  -  Batch Platform  -  INC-5502")
        canvas.drawRightString(A4[0] - 25 * mm, 12 * mm, "%d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=22 * mm,
                            bottomMargin=20 * mm, leftMargin=25 * mm,
                            rightMargin=25 * mm,
                            title="INC-5502 settlement export skipped on DST change",
                            author="h.lindqvist")
    s = []
    s.append(P("INC-5502: Settlement export did not run on the night clocks went "
               "forward", ParagraphStyle("t11", parent=H1, textColor=INK)))
    s.append(P("Post-incident review &middot; H. Lindqvist, Batch Platform &middot; "
               "reviewed 2026-04-02", SMALL))
    s.append(Spacer(1, 6))
    s.append(kv_table([
        ("Jira issue", "INC-5502 &nbsp;(actions BAT-301 to BAT-304)"),
        ("Severity", "SEV-2 (major)"),
        ("Service", "settlement-export, jobrunner 4.2 (Quartz scheduler)"),
        ("Environment", "Production &mdash; batch-02"),
        ("Missed run", "2026-03-29, scheduled 02:30 Europe/Zurich"),
        ("Detected", "2026-03-30 07:40 CEST &mdash; e-mail from the acquirer"),
        ("Resolved", "2026-03-30 11:15 CEST"),
        ("Affected systems", "settlement-export, jobrunner"),
    ], W, label_bg=colors.HexColor("#E8F4F4")))

    s.append(P("Summary", H))
    s.append(P(
        "The nightly settlement export, which sends the previous day's card "
        "transactions to our acquirer Helvetic Clearing, did not run on Sunday 29 "
        "March 2026. Nothing failed and nothing was logged as an error: the job "
        "simply never started. Its absence was noticed on Monday morning when the "
        "acquirer reported that no file had arrived for Saturday's business day. "
        "The export was run by hand at 10:52 and the file accepted at 11:15.", BODY))

    s.append(P("Impact", H))
    s.extend(bullets([
        "38,400 card transactions from 28 March settled one business day late.",
        "CHF 7,850 in late-settlement fees charged by the acquirer, confirmed by "
        "Finance on 1 April.",
        "No transactions were lost or duplicated. Merchants saw payouts one day "
        "later than usual; 19 merchant support contacts.",
    ]))

    s.append(P("Timeline (CEST unless stated)", H))
    s.append(grid_table(
        ["When", "What happened"],
        [["2025-11-18", "settlement-export migrated from cron to jobrunner. Trigger "
          "defined as <font face='Courier'>0 30 2 * * ?</font> in time zone "
          "Europe/Zurich, misfire policy <font face='Courier'>DO_NOTHING</font>."],
         ["2026-03-29 02:00 CET", "Clocks go forward to 03:00 CEST. The local time "
          "02:30 does not occur on this date."],
         ["2026-03-29", "jobrunner computes the next fire time, finds 02:30 "
          "unrepresentable, treats the fire as missed and, per DO_NOTHING, schedules "
          "the next one for 30 March. No log line above DEBUG."],
         ["2026-03-30 02:30", "Export runs normally for Sunday's business day. "
          "Saturday's is still missing."],
         ["2026-03-30 07:40", "Helvetic Clearing e-mails settlement operations: no "
          "file received for 28 March."],
         ["2026-03-30 08:05", "H. Lindqvist on-call; INC-5502 raised as SEV-2."],
         ["2026-03-30 08:40", "jobrunner history shows no execution record for 29 "
          "March. DST transition identified as the reason."],
         ["2026-03-30 10:52", "Export for 28 March run by hand with the backfill "
          "flag."],
         ["2026-03-30 11:15", "Acquirer confirms the file is accepted. Resolved."],
         ["2026-04-02", "Review held with Batch Platform and Settlement Ops."]],
        [30 * mm, W - 30 * mm], head_bg=TEAL, cell_style=TABLE_S))

    s.append(P("Root cause", H))
    s.append(panel([P(
        "The trigger was expressed in local wall-clock time, 02:30 Europe/Zurich, "
        "and on the day of the spring daylight-saving transition that time does not "
        "exist. jobrunner treats a fire time that cannot occur as a misfire, and the "
        "job was configured with the DO_NOTHING misfire policy, so the run for 29 "
        "March was skipped without an error, an alert or a retry. The job had been "
        "on jobrunner since November 2025, so this was its first spring "
        "transition.", BODY)], W, bg=colors.HexColor("#E8F4F4"), bar=TEAL))
    s.append(P(
        "Contributing: our batch alerting fires on a failed run, and a run that "
        "never starts cannot fail. There was no check that each expected run "
        "actually happened.", BODY))

    s.append(P("Action plan", H))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["BAT-301", "Define every production jobrunner trigger in UTC; migrate the "
          "41 existing local-time triggers.", "H. Lindqvist", "2026-04-17", "Done"],
         ["BAT-302", "Alert when an expected scheduled run has not started within "
          "15 minutes of its fire time.", "M. Dubois", "2026-04-10", "Done"],
         ["BAT-303", "CI lint that rejects any trigger with a local time zone "
          "between 01:00 and 03:59.", "H. Lindqvist", "2026-04-24", "Done"],
         ["BAT-304", "Change the default misfire policy for settlement jobs to "
          "FIRE_ONCE_NOW.", "K. Oyelaran", "2026-04-10", "Done"]],
        [17 * mm, W - 75 * mm, 22 * mm, 20 * mm, 16 * mm], head_bg=TEAL,
        cell_style=TABLE_S))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ============================================= 12 - status report with tiles ==

def doc_12():
    path = OUT / "INC-5517-beta-pricing-exposed-flag-upgrade.pdf"
    W = A4[0] - 36 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#5B2C6F"))
        canvas.rect(0, A4[1] - 18 * mm, A4[0], 18 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(18 * mm, A4[1] - 11 * mm, "Incident status report")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 11 * mm,
                               "Helvetica Retail AG  |  Digital Commerce")
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(18 * mm, 10 * mm, "INC-5517  |  final  |  2026-06-15")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, "page %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=24 * mm,
                            bottomMargin=16 * mm, leftMargin=18 * mm,
                            rightMargin=18 * mm,
                            title="INC-5517 beta pricing exposed to all customers",
                            author="n.vogel")
    s = []
    s.append(P("Beta discounts shown to every storefront customer for two hours",
               H1))
    s.append(P("INC-5517 &middot; SEV-2 &middot; author N. Vogel (Commerce "
               "Platform) &middot; final version 2026-06-15", SMALL))
    s.append(Spacer(1, 5))
    s.append(tiles([
        ("Duration", "2h 06m", "10:56 - 13:02 CEST, 2026-06-09"),
        ("Orders affected", "4,310", "placed at the beta price"),
        ("Margin lost", "CHF 61,700", "all orders honoured"),
        ("Deployments", "0", "no application change that day"),
    ], W, value_color=colors.HexColor("#5B2C6F")))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("Jira issue", "INC-5517 &middot; actions COM-770 to COM-773"),
        ("Severity", "SEV-2 (major)"),
        ("Resolved", "2026-06-09 13:02 CEST"),
        ("Affected systems", "toggle (feature flag service), storefront-web, "
                             "pricing-service"),
        ("Incident lead", "N. Vogel"),
    ], W))

    s.append(P("What happened", H2))
    s.append(P(
        "At 10:56 CEST on 9 June 2026 every customer of the Swiss storefront began "
        "seeing the beta discount programme: 12% off selected home and garden "
        "categories, which had been exposed to 5% of logged-in customers since 20 "
        "May. The merchandising team noticed the margin dashboard diverging at "
        "11:30 and raised the incident at 11:41. The discount was withdrawn at "
        "13:02 by correcting a single flag value.", BODY))
    s.append(P(
        "<b>No application deployment took place on 9 June.</b> pricing-service was "
        "last deployed on 2 June and storefront-web on 4 June; both were ruled out "
        "in the first twenty minutes of the investigation. The only production "
        "change that morning was the upgrade of the feature flag service, toggle, "
        "from 2.14 to 3.0 at 10:54.", BODY))

    s.append(P("Root cause", H2))
    s.append(panel([P(
        "toggle 3.0 changed the meaning of a flag's <font face='Courier'>rollout"
        "</font> field from a percentage (0&ndash;100) to a fraction (0.0&ndash;"
        "1.0), and clamps any value above 1.0 to 1.0. The flag "
        "<font face='Courier'>pricing.beta-discounts</font> held the value "
        "<font face='Courier'>5</font>, meaning 5% under 2.x; under 3.0 it was "
        "read as 5.0, clamped to 1.0, and served to 100% of customers. The upgrade "
        "shipped a migration script that divides every rollout by 100, but the "
        "script only walks flags created through the toggle UI. Flags in the "
        "<font face='Courier'>pricing</font> namespace are managed by Terraform "
        "and were never migrated.", BODY)],
        W, bg=colors.HexColor("#F3EAF7"), bar=colors.HexColor("#5B2C6F")))

    s.append(P("Timeline (CEST, 2026-06-09)", H2))
    s.append(grid_table(
        ["Time", "Event"],
        [["10:54", "toggle upgraded 2.14 &rarr; 3.0 (change COM-CHG-2208). UI "
          "migration script runs; 212 flags migrated."],
         ["10:56", "pricing.beta-discounts begins evaluating true for every "
          "customer."],
         ["11:30", "Merchandising sees gross margin 9 points below forecast."],
         ["11:41", "INC-5517 raised, SEV-2. N. Vogel leads."],
         ["11:58", "Deployment history checked: nothing deployed to pricing or "
          "storefront since 4 June."],
         ["12:31", "Flag evaluation logs show 100% true for the beta flag since "
          "10:56; toggle upgrade correlated."],
         ["12:47", "Unit change in toggle 3.0 release notes identified."],
         ["13:02", "Rollout set to 0.05 via Terraform. Discount withdrawn. "
          "Resolved."]],
        [16 * mm, W - 16 * mm], head_bg=colors.HexColor("#5B2C6F"),
        cell_style=TABLE_S))

    s.append(P("Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["COM-770", "Migrate every Terraform-managed flag to fractional rollout "
          "and add a plan-time check that rejects rollout values above 1.0.",
          "N. Vogel", "2026-06-19", "Done"],
         ["COM-771", "Treat flag service upgrades as production changes requiring a "
          "diff of effective evaluation for the top 50 flags.", "L. Reber",
          "2026-06-30", "Done"],
         ["COM-772", "Alert when any pricing flag's true-rate changes by more than "
          "10 points in 5 minutes.", "A. Novak", "2026-06-26", "Done"],
         ["COM-773", "Margin-divergence alert for merchandising, paging at 3 points "
          "below forecast for 15 minutes.", "N. Vogel", "2026-07-03", "Done"]],
        [17 * mm, W - 75 * mm, 20 * mm, 20 * mm, 18 * mm],
        head_bg=colors.HexColor("#5B2C6F"), cell_style=TABLE_S))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# =========================================== 13 - security-team report =======

def doc_13():
    path = OUT / "INC-5563-public-api-saturation-not-ddos.pdf"
    W = A4[0] - 40 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RED)
        canvas.setLineWidth(3)
        canvas.line(20 * mm, A4[1] - 14 * mm, A4[0] - 20 * mm, A4[1] - 14 * mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(RED)
        canvas.drawString(20 * mm, A4[1] - 11 * mm, "NORTHWIND PAYMENTS  -  "
                                                   "SECURITY & RELIABILITY")
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 11 * mm,
                               "TLP:AMBER  -  INC-5563")
        canvas.drawString(20 * mm, 10 * mm, "Joint review: SecOps and API Platform"
                                            "  -  issued 2026-07-21")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, "%d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm,
                            bottomMargin=16 * mm, leftMargin=20 * mm,
                            rightMargin=20 * mm,
                            title="INC-5563 public API saturation",
                            author="e.baumann")
    s = []
    s.append(P("Public API saturated for 47 minutes: suspected attack, "
               "confirmed partner retry loop", H1))
    s.append(P("INC-5563 &middot; SEV-1 &middot; E. Baumann (SecOps) and "
               "T. Iversen (API Platform) &middot; 2026-07-21", SMALL))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("Jira issue", "INC-5563 &middot; actions API-2240 to API-2244"),
        ("Severity", "SEV-1 (critical)"),
        ("Window", "2026-07-14 09:02 &ndash; 09:49 CEST"),
        ("Resolved", "2026-07-14 09:49 CEST"),
        ("Affected systems", "public-api-gateway, auth-token-service"),
        ("Security impact", "None. No credential compromise, no data access."),
    ], W))

    s.append(P("1. Description", H2))
    s.append(P(
        "From 09:02 CEST on 14 July 2026 the public API gateway was saturated at "
        "roughly 38,000 requests per second against a normal peak of 4,500. 61% of "
        "requests from all other API clients failed with 503 or timed out. Because "
        "the traffic spike was sudden and an order of magnitude above normal, the "
        "incident was opened as a suspected DDoS and SecOps took command.", BODY))

    s.append(P("2. Impact", H2))
    s.extend(bullets([
        "47 minutes of severe degradation for every API client.",
        "CHF 23,400 in SLA credits owed to 14 merchants under the API agreement.",
        "No data exposure; every request in the spike failed authentication.",
    ]))

    s.append(P("3. Hypotheses considered", H2))
    s.append(grid_table(
        ["Hypothesis", "Evidence", "Outcome"],
        [["Volumetric DDoS against the public API",
          "WAF logs: 97% of the spike carried one partner's client id and came "
          "from that partner's registered egress range; no botnet signature; no "
          "spread across source networks.",
          "<b>Ruled out at 09:24.</b>"],
         ["Credential-stuffing attack",
          "All requests presented the same client id with a single expired access "
          "token; no variation in credentials.",
          "<b>Ruled out at 09:24.</b>"],
         ["Partner client malfunction",
          "Partner Kestrel Travel confirmed a deploy of their booking backend at "
          "08:40 and reproduced the loop in their staging environment.",
          "<b>Confirmed at 09:41.</b>"]],
        [42 * mm, W - 72 * mm, 30 * mm], head_bg=RED, cell_style=TABLE_S))

    s.append(P("4. Root cause", H2))
    s.append(panel([P(
        "Kestrel Travel's new booking backend retried every HTTP 401 immediately, "
        "without backoff and without refreshing its access token, across 1,200 "
        "worker threads. When the token expired at 09:00 every worker entered a "
        "tight retry loop. On our side, the gateway applied per-client rate limits "
        "only <i>after</i> successful authentication, so requests that failed "
        "authentication were never counted against the partner's quota and nothing "
        "throttled the loop. Either fault alone would have been contained: the "
        "partner's bug would have been rate-limited, and our ordering would not "
        "have mattered without a client retrying at that volume.", BODY)],
        W, bg=colors.HexColor("#FBE5E5"), bar=RED))

    s.append(P("5. Timeline (CEST, 2026-07-14)", H2))
    s.append(grid_table(
        ["Time", "Event"],
        [["08:40", "Kestrel Travel deploys booking backend 5.0."],
         ["09:00", "Kestrel's access token expires."],
         ["09:02", "Gateway request rate passes 30,000/s. API-5XX alert pages."],
         ["09:06", "SEV-1 declared as suspected DDoS; E. Baumann takes command."],
         ["09:24", "WAF analysis rules out DDoS and credential stuffing."],
         ["09:31", "Kestrel's client id blocked at the edge. Gateway recovers "
          "partially."],
         ["09:41", "Kestrel confirms the retry loop and rolls back."],
         ["09:49", "Block lifted with a temporary 200 req/s cap. Resolved."],
         ["07-21", "Joint review with Kestrel Travel attending."]],
        [16 * mm, W - 16 * mm], head_bg=RED, cell_style=TABLE_S))

    s.append(P("6. Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["API-2240", "Count failed-authentication requests against the presenting "
          "client id's rate limit, before authentication completes.", "T. Iversen",
          "2026-07-31", "Done"],
         ["API-2241", "Per-client circuit breaker: 1,000 consecutive 401s blocks "
          "the client id for 5 minutes.", "T. Iversen", "2026-08-07", "Done"],
         ["API-2242", "Publish retry and token-refresh requirements in the partner "
          "API terms; require backoff on 401 and 429.", "L. Reber", "2026-08-14",
          "Done"],
         ["API-2243", "Runbook: distinguish a single-client flood from a DDoS "
          "within 5 minutes using WAF client-id breakdown.", "E. Baumann",
          "2026-07-28", "Done"],
         ["API-2244", "Partner onboarding load test that includes token expiry.",
          "T. Iversen", "2026-08-21", "Done"]],
        [18 * mm, W - 76 * mm, 20 * mm, 20 * mm, 18 * mm], head_bg=RED,
        cell_style=TABLE_S))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ============================================== 14 - DR exercise record ======

def doc_14():
    path = OUT / "INC-5608-backups-expired-by-lifecycle-rule.pdf"
    W = A4[0] - 40 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#E9F2E9"))
        canvas.rect(0, A4[1] - 20 * mm, A4[0], 20 * mm, stroke=0, fill=1)
        canvas.setFillColor(GREEN)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(20 * mm, A4[1] - 12 * mm,
                          "Disaster Recovery Exercise DR-2026-Q2  -  Finding record")
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(20 * mm, A4[1] - 16.5 * mm,
                          "Helvetica Retail AG  -  Infrastructure Resilience")
        canvas.drawString(20 * mm, 10 * mm, "Raised as INC-5608 because the finding "
                                            "was a live production risk")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, "%d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=26 * mm,
                            bottomMargin=16 * mm, leftMargin=20 * mm,
                            rightMargin=20 * mm,
                            title="INC-5608 database backups expired by lifecycle "
                                  "rule", author="s.caduff")
    s = []
    s.append(P("Database backups older than seven days did not exist", H1))
    s.append(P("INC-5608 &middot; found during DR-2026-Q2 &middot; S. Caduff "
               "(Infrastructure Resilience) &middot; closed 2026-05-22", SMALL))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("Jira issue", "INC-5608 &middot; actions RES-410 to RES-413"),
        ("Severity", "SEV-2 (major) &mdash; latent data-loss exposure; no "
                     "customer impact"),
        ("Found", "2026-05-12 14:20 CEST, DR exercise step 7 (restore from 30 "
                  "days ago)"),
        ("Resolved", "2026-05-15 17:00 CEST"),
        ("Financial impact", "CHF 0 &mdash; no data was lost and no restore was "
                             "needed in production"),
        ("Affected systems", "backup-orchestrator, bucket hr-prod-db-backups"),
    ], W, label_bg=colors.HexColor("#E9F2E9")))

    s.append(P("Description", H2))
    s.append(P(
        "The quarterly DR exercise on 12 May 2026 includes restoring the customer "
        "database as it stood 30 days earlier. The restore failed at step 7 because "
        "no backup older than seven days existed in the backup bucket. Our backup "
        "policy requires 35 days of daily backups. The nightly backup job had "
        "succeeded every night; the backups it wrote were being deleted a week "
        "later.", BODY))
    s.append(P(
        "For 82 days, from 19 February to 12 May, any corruption or deletion "
        "discovered more than a week after the fact could not have been recovered "
        "from backup. No such event occurred in that period.", BODY))

    s.append(Spacer(1, 3))
    s.append(line_chart(
        [[35, 35, 35, 7, 7, 7, 7, 7, 7, 35]],
        ["1 Feb", "10 Feb", "18 Feb", "19 Feb", "1 Mar", "1 Apr", "1 May",
         "12 May", "15 May", "19 Jun"],
        width=W, height=42 * mm, colours=(GREEN,), y_min=0, y_max=40, y_step=10,
        title="Restorable daily backups held in hr-prod-db-backups"))
    s.append(P("Figure 1 &mdash; retention falls from 35 to 7 on 19 February and "
               "returns to 35 once the lifecycle rule is removed and a month of "
               "backups has accumulated again.", CAPTION))

    s.append(P("Root cause", H2))
    s.append(panel([P(
        "On 19 February 2026 a storage cost-reduction change, FINOPS-118, applied a "
        "standard lifecycle rule to every bucket whose name begins "
        "<font face='Courier'>hr-prod-</font>. The rule expires objects seven days "
        "after creation. It was written for log buckets, and the backup bucket "
        "<font face='Courier'>hr-prod-db-backups</font> matched the prefix. The "
        "change was reviewed by FinOps, who did not know the bucket held backups; "
        "the bucket carried no tag saying so.", BODY_S),
        P("The exposure lasted 82 days because backup monitoring checks only that "
          "last night's backup was written. Nothing verified that the oldest "
          "required backup still existed.", BODY_S)],
        W, bg=colors.HexColor("#E9F2E9"), bar=GREEN))

    s.append(P("Timeline", H2))
    s.append(grid_table(
        ["When", "What happened"],
        [["2026-02-19 10:30", "FINOPS-118 applied: 7-day expiry on all hr-prod-* "
          "buckets (31 buckets)."],
         ["2026-02-26", "First backup deleted by the rule."],
         ["2026-05-12 14:20", "DR step 7 fails: oldest backup is dated 5 May."],
         ["2026-05-12 14:45", "Lifecycle rule found on the bucket. INC-5608 "
          "raised."],
         ["2026-05-12 15:30", "Rule removed from hr-prod-db-backups and from two "
          "other buckets holding backups."],
         ["2026-05-13", "Second, independent backup copy to the DR region "
          "started, to cover the 35-day window while it refills."],
         ["2026-05-15 17:00", "Controls in place; exposure reduced to the refill "
          "period. Resolved."],
         ["2026-05-22", "Review held; incident closed."]],
        [30 * mm, W - 30 * mm], head_bg=GREEN, cell_style=TABLE_S))

    s.append(P("Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["RES-410", "Tag every bucket holding backups data-class=backup and deny "
          "lifecycle rules on that tag by policy.", "S. Caduff", "2026-05-29",
          "Done"],
         ["RES-411", "Daily check that the oldest required backup (day 35) exists "
          "and is restorable; page on failure.", "A. Novak", "2026-06-05", "Done"],
         ["RES-412", "Lifecycle changes by prefix require a listing of every "
          "matched bucket in the change record.", "FinOps (J. Meier)",
          "2026-06-12", "Done"],
         ["RES-413", "Move the 30-day restore from the quarterly DR exercise into a "
          "weekly automated test.", "S. Caduff", "2026-06-26", "Done"]],
        [17 * mm, W - 79 * mm, 26 * mm, 20 * mm, 16 * mm], head_bg=GREEN,
        cell_style=TABLE_S))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ============================================ 15 - issue tracker export =======

def doc_15():
    path = OUT / "INC-5641-checkout-5xx-deploy-migration-lock.pdf"
    W = A4[0] - 36 * mm
    META = ParagraphStyle("meta15", parent=MONO_S, textColor=GREY)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#FAFBFC"))
        canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#FC6D26"))
        canvas.rect(0, A4[1] - 3 * mm, A4[0], 3 * mm, stroke=0, fill=1)
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, A4[1] - 9 * mm,
                          "northwind / platform / incidents  >  Issues  >  "
                          "INC-5641")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm,
                               "exported 2026-09-01  -  page %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=15 * mm,
                            bottomMargin=15 * mm, leftMargin=18 * mm,
                            rightMargin=18 * mm,
                            title="INC-5641 checkout 5xx during deploy",
                            author="d.fischer")
    s = []
    s.append(P("Checkout 5xx during checkout-api 12.4.0 rollout", H1))
    s.append(P("INC-5641 &nbsp;&middot;&nbsp; <font color='#1F7A3E'><b>Closed"
               "</b></font> &nbsp;&middot;&nbsp; opened by d.fischer on 2026-08-24 "
               "&nbsp;&middot;&nbsp; labels: incident, sev::2, postmortem-done",
               SMALL))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("Severity", "SEV-2 (major)"),
        ("Window", "2026-08-24 14:07 &ndash; 14:26 CEST (19 minutes)"),
        ("Resolved", "2026-08-24 14:26 CEST"),
        ("Affected systems", "checkout-api, orders-db"),
        ("Linked", "PLAT-951, PLAT-952, PLAT-953"),
    ], W, label_bg=colors.HexColor("#F0F2F5")))

    s.append(P("Description", H2))
    s.append(P(
        "During the rolling deploy of checkout-api 12.4.0, 8.2% of checkout "
        "requests failed with 502 or 504 for 19 minutes. Every failing request was "
        "routed to a newly started pod. Pods that had not yet been replaced served "
        "normally. We estimate CHF 14,900 of lost revenue from customers who did "
        "not retry.", BODY))

    s.append(P("Root cause", H2))
    s.append(P(
        "<b>Two causes were jointly necessary; neither alone would have produced "
        "customer impact.</b>", BODY))
    s.extend(bullets([
        "<b>A startup migration held a table lock.</b> 12.4.0 added an index to "
        "<font face='Courier'>orders_idempotency</font> through a migration that "
        "runs on application startup, without "
        "<font face='Courier'>CONCURRENTLY</font>. The first new pod took an "
        "exclusive lock on the table for about four minutes, and every request "
        "needing that table blocked behind it, on every pod that tried to start "
        "while the lock was held.",
        "<b>The readiness probe did not check readiness.</b> The probe pointed at "
        "<font face='Courier'>/healthz</font>, which returns 200 as soon as the HTTP "
        "server is listening. New pods were marked ready and received traffic "
        "while still blocked on the migration. Had the probe pointed at "
        "<font face='Courier'>/ready</font>, those pods would have been held out of "
        "rotation and the old pods would have kept serving.",
    ]))

    s.append(P("Timeline (CEST)", H2))
    s.append(P(
        "14:05 &nbsp;deploy of 12.4.0 starts (25% surge)<br/>"
        "14:07 &nbsp;first new pod ready per /healthz; migration takes lock<br/>"
        "14:09 &nbsp;CHECKOUT-5XX alert fires; d.fischer acknowledges<br/>"
        "14:14 &nbsp;SEV-2 declared; deploy paused<br/>"
        "14:19 &nbsp;pg_locks shows AccessExclusiveLock on orders_idempotency held by "
        "the migration<br/>"
        "14:21 &nbsp;migration completes; lock released<br/>"
        "14:26 &nbsp;new pods drain their queues; error rate at baseline; "
        "resolved<br/>"
        "08-27 &nbsp;review held", MONO_S))

    s.append(Spacer(1, 3))
    s.append(bar_chart(
        [[0.1, 0.2, 6.9, 8.2, 7.7, 3.4, 0.2, 0.1]],
        ["14:00", "14:05", "14:08", "14:12", "14:16", "14:21", "14:26", "14:30"],
        width=W, height=36 * mm, colours=(colors.HexColor("#FC6D26"),),
        y_max=10, y_step=2, title="checkout 5xx rate, %"))

    s.append(P("Action items", H2))
    s.append(grid_table(
        ["Issue", "Action", "Owner", "Due", "State"],
        [["PLAT-951", "Remove schema migrations from application startup; run them "
          "as a separate, pre-deploy job with a lock timeout.", "d.fischer",
          "2026-09-11", "Closed"],
         ["PLAT-952", "Point readiness probes at /ready on every service; fail CI "
          "when a readiness probe targets /healthz.", "p.almeida", "2026-09-04",
          "Closed"],
         ["PLAT-953", "Migration linter: reject CREATE INDEX without CONCURRENTLY "
          "on tables above 1 GB.", "k.oyelaran", "2026-09-18", "Closed"]],
        [18 * mm, W - 76 * mm, 22 * mm, 20 * mm, 16 * mm],
        head_bg=colors.HexColor("#303030"), cell_style=TABLE_S))
    s.append(Spacer(1, 4))
    s.append(P("d.fischer closed this issue on 2026-09-01 &middot; 9 comments "
               "hidden in export", META))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ================================================ 16 - German memo ============

def doc_16():
    path = OUT / "INC-5699-kassenterminals-offline-firewall.pdf"
    W = A4[0] - 44 * mm
    SH = ParagraphStyle("sh16", parent=SERIF_H, textColor=NAVY)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(NAVY)
        canvas.drawString(22 * mm, A4[1] - 14 * mm, "HELVETICA RETAIL AG")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(22 * mm, A4[1] - 18 * mm,
                          "IT-Betrieb Filialen  ·  Störungsbericht")
        canvas.drawRightString(A4[0] - 22 * mm, A4[1] - 14 * mm, "INC-5699")
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(0.8)
        canvas.line(22 * mm, A4[1] - 20 * mm, A4[0] - 22 * mm, A4[1] - 20 * mm)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(22 * mm, 11 * mm, "Intern · Freigabe: J. Keller, "
                                            "2026-09-10")
        canvas.drawRightString(A4[0] - 22 * mm, 11 * mm, "Seite %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=26 * mm,
                            bottomMargin=18 * mm, leftMargin=22 * mm,
                            rightMargin=22 * mm,
                            title="INC-5699 Störungsbericht Kassenterminals",
                            author="r.brunner")
    s = []
    s.append(P("Störungsbericht: Kartenzahlungen in 42 Filialen nicht "
               "möglich", ParagraphStyle("t16", parent=H1, fontName="Times-Bold",
                                              textColor=NAVY)))
    s.append(P("Verfasst von R. Brunner (Netzwerk Filialen) &middot; besprochen am "
               "2026-09-09", SMALL))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("Jira-Ticket", "INC-5699 &middot; Massnahmen NET-1502 bis NET-1505"),
        ("Schweregrad", "SEV-1 (kritisch)"),
        ("Datum", "Samstag, 5. September 2026"),
        ("Dauer", "1 Std. 23 Min. (10:12 &ndash; 11:35 Uhr)"),
        ("Behoben", "2026-09-05 11:35 Uhr"),
        ("Betroffene Systeme", "store-firewall, payment-terminal-host"),
    ], W, s=ParagraphStyle("kv16", parent=SERIF, fontSize=8.5, leading=11,
                           spaceAfter=0)))

    s.append(P("1. Beschreibung", SH))
    s.append(P(
        "Am Samstag, 5. September 2026, konnten ab 10:12 Uhr die Kassenterminals in "
        "42 von 118 Filialen keine Kartenzahlungen mehr autorisieren. Die Terminals "
        "meldeten «Host nicht erreichbar». Barzahlungen waren weiterhin "
        "möglich. In mehreren Filialen bildeten sich lange Warteschlangen, und "
        "Kundinnen und Kunden verliessen die Filiale ohne Einkauf.", SERIF))

    s.append(P("2. Auswirkungen", SH))
    s.extend(bullets([
        "Rund 3'900 Kartenzahlungen abgelehnt.",
        "Geschätzter Umsatzverlust: CHF 36'500 (Hochrechnung aus dem "
        "Vorjahres-Samstag).",
        "Keine Daten betroffen; keine Zahlung doppelt verbucht.",
    ], SERIF))

    s.append(P("3. Ursache", SH))
    s.append(panel([P(
        "Die Firewall-Änderung NET-CHG-9120 sollte einen als ungenutzt "
        "eingestuften Portbereich (TCP 9000&ndash;9010) im Filialnetz schliessen. "
        "Die Kassenterminals verbinden sich jedoch über TCP-Port 9001 mit dem "
        "Payment-Terminal-Host. Der Portbereich war als ungenutzt eingestuft "
        "worden, weil die Auswertung auf den Flow-Logs der letzten 30 Tage beruhte "
        "&ndash; und das VLAN der Kassenterminals wird von der Flow-Protokollierung "
        "nicht erfasst. Die Änderung wurde um 10:10 Uhr gestaffelt auf die "
        "Filialen der Region Mitte und West ausgerollt, daher waren nur 42 Filialen "
        "betroffen.", SERIF)], W, bg=colors.HexColor("#EAF0F8"), bar=NAVY))

    s.append(P("4. Zeitablauf (Ortszeit)", SH))
    s.append(grid_table(
        ["Zeit", "Ereignis"],
        [["10:10", "NET-CHG-9120 wird auf die Filialen Mitte und West "
          "ausgerollt."],
         ["10:12", "Erste Terminals melden «Host nicht erreichbar»."],
         ["10:19", "Service Desk erhält die ersten Anrufe aus Filialen."],
         ["10:31", "SEV-1 ausgerufen; R. Brunner übernimmt die Leitung."],
         ["10:58", "Zusammenhang mit NET-CHG-9120 erkannt; Port 9001 als "
          "Terminal-Port identifiziert."],
         ["11:20", "Firewall-Änderung zurückgenommen."],
         ["11:35", "Alle Terminals wieder verbunden. Störung behoben."],
         ["09.09.", "Nachbesprechung mit Netzwerk, Filialbetrieb und Change "
          "Management."]],
        [18 * mm, W - 18 * mm], head_bg=NAVY,
        cell_style=ParagraphStyle("t16c", parent=SERIF, fontSize=8, leading=10.5,
                                  spaceAfter=0)))

    s.append(P("5. Massnahmen", SH))
    s.append(grid_table(
        ["Ticket", "Massnahme", "Verantwortlich", "Fällig", "Status"],
        [["NET-1502", "Flow-Protokollierung auf das Terminal-VLAN ausweiten.",
          "R. Brunner", "2026-09-18", "Offen"],
         ["NET-1503", "Portfreigaben für Kassenterminals als geschützte "
          "Regeln markieren; Änderungen daran nur mit Freigabe des "
          "Filialbetriebs.", "R. Brunner", "2026-09-25", "Offen"],
         ["NET-1504", "Firewall-Änderungen im Filialnetz zuerst in zwei "
          "Pilotfilialen ausrollen, mit Testzahlung vor dem Rollout.",
          "L. Reber", "2026-09-30", "Offen"],
         ["NET-1505", "Keine Firewall-Änderungen an Samstagen im "
          "Filialnetz.", "J. Keller", "2026-09-12", "Erledigt"]],
        [18 * mm, W - 76 * mm, 26 * mm, 18 * mm, 14 * mm], head_bg=NAVY,
        cell_style=ParagraphStyle("t16d", parent=SERIF, fontSize=8, leading=10.5,
                                  spaceAfter=0)))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


ALL = [doc_11, doc_12, doc_13, doc_14, doc_15, doc_16]
