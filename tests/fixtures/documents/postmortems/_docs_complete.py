"""The five complete postmortems (fixtures 01-05).

Each one has: a Jira ID, a dated timeline, a description with impact, a stated
root cause, and an action plan with more than one owned, dated item. Layouts
differ on purpose - corporate template, engineering plain text, wiki export,
two-column, landscape one-pager.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from _common import (
    AMBER, BODY, BODY_S, CAPTION, GREEN, GREY, H1, H2, H2_PLAIN, INK, LIGHT, LIGHT as _L,
    MONO, MONO_S, NAVY, OUT, P, PANEL_BG, RED, RULE, SMALL, STEEL, TEAL,
    ParagraphStyle, bar_chart, bullets, dashboard_screenshot, grid_table, kv_table,
    line_chart, panel, pie_chart, request_path_diagram, tiles, wave_sparkline,
)


# ============================================================ 01 - corporate =

COMPACT = ParagraphStyle("compact", parent=BODY_S, fontSize=7.2, leading=9.2)
TIGHT_MONO = ParagraphStyle("tightmono", parent=MONO_S, fontSize=6.8, leading=8.6)


def doc_01():
    path = OUT / "INC-4830-postmortem-checkout-tls-expiry.pdf"
    W = A4[0] - 40 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - 22 * mm, A4[0], 22 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(20 * mm, A4[1] - 13 * mm, "NORTHWIND PAYMENTS")
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20 * mm, A4[1] - 18 * mm,
                          "Service Reliability  |  Post-Incident Review")
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 13 * mm, "INC-4830")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 18 * mm, "SEV-1  |  CLOSED")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(20 * mm, 11 * mm,
                          "INTERNAL - post-incident review  |  Rev 2 (2026-08-05)")
        canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, "Page %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=28 * mm,
                            bottomMargin=20 * mm, leftMargin=20 * mm,
                            rightMargin=20 * mm,
                            title="INC-4830 Post-Incident Review",
                            author="s.hartmann", subject="Postmortem")
    s = []
    s.append(P("Checkout unavailable in production &mdash; expired TLS "
               "certificate on the payment gateway", H1))
    s.append(P("Post-incident review &middot; prepared by S. Hartmann (SRE) &middot; "
               "reviewed by the Payments guild on 2026-08-04", SMALL))
    s.append(Spacer(1, 6))
    s.append(kv_table([
        ("Jira issue", "INC-4830 &nbsp;(linked: OPS-3312 &lsquo;Certificate "
                       "inventory&rsquo;, PAY-1190)"),
        ("Severity", "SEV-1 &mdash; complete loss of a revenue-critical function"),
        ("Environment", "Production &mdash; eu-central-1, eu-west-1"),
        ("Service", "payments-gateway (v4.18.2), checkout-web (v11.6.0)"),
        ("Detected", "2026-07-28 06:12 CEST &mdash; automated (synthetic checkout probe)"),
        ("Resolved", "2026-07-28 07:04 CEST"),
        ("Duration", "52 minutes of total unavailability; 71 minutes of degradation"),
        ("Incident commander", "S. Hartmann &middot; Comms: L. Reber &middot; "
                               "Ops: M. Dubois"),
        ("Status", "Closed &mdash; all actions completed 2026-08-19"),
    ], W))

    s.append(P("1. What happened", H2))
    s.append(P(
        "At 06:12 CEST on Tuesday 28 July 2026 the public checkout flow began "
        "returning HTTP 502 for every payment authorisation request. The "
        "payments-gateway service could not open a TLS session to the acquirer "
        "endpoint <font face='Courier'>acq-gw.prod.northwind.internal</font> "
        "because the server certificate presented by the internal load balancer "
        "had expired at 06:11:58 CEST. Customers reaching the payment step saw a "
        "generic error page and could not complete an order. Browsing, search and "
        "basket operations were unaffected.", BODY))
    s.append(P(
        "The outage lasted 52 minutes. Service was restored at 07:04 by installing "
        "the renewed certificate, which had been issued on 12 July but never "
        "deployed, and reloading the load balancer configuration.", BODY))

    s.append(P("2. Impact", H2))
    s.append(grid_table(
        ["Dimension", "Measured impact"],
        [["Failed checkouts", "9,431 authorisation attempts rejected (100% of "
                              "attempts in the window)"],
         ["Customers affected", "6,802 unique sessions; 148 support contacts"],
         ["Revenue deferred", "CHF 412,900 in basket value; CHF 48,200 estimated "
                              "as permanently lost (non-returning sessions)"],
         ["SLO", "Monthly availability budget for checkout consumed: 71% in a "
                 "single event"],
         ["Regulatory", "None. No card data exposed; no reportable data breach."]],
        [38 * mm, W - 38 * mm], cell_style=COMPACT))

    s.append(Spacer(1, 6))
    s.append(line_chart(
        [[99.4, 99.5, 99.3, 62.0, 3.1, 2.8, 3.0, 71.4, 99.1, 99.4]],
        ["05:30", "05:50", "06:10", "06:20", "06:30", "06:40", "06:50", "07:05",
         "07:20", "07:40"],
        width=W, height=46 * mm, colours=(STEEL,),
        y_min=0, y_max=100, y_step=25,
        title="Checkout authorisation success rate, % (2026-07-28, CEST)",
        band=(2.5, 7.0)))
    s.append(P("Figure 1 &mdash; shaded region is the incident window. Recovery is "
               "partial at 07:05 because eu-west-1 was reloaded four minutes after "
               "eu-central-1.", CAPTION))

    s.append(P("3. Timeline (all times CEST)", H2))
    s.append(grid_table(
        ["Time", "Actor", "Event"],
        [["2026-07-12 09:40", "cert-manager", "Renewed certificate issued for "
          "*.prod.northwind.internal and written to Vault. No deployment step is "
          "triggered by issuance."],
         ["2026-07-27 18:00", "&mdash;", "Change freeze for the quarter-end release "
          "begins. Routine infrastructure changes are paused."],
         ["06:11:58", "&mdash;", "Certificate on lb-acq-01/02 expires."],
         ["06:12", "Synthetic probe", "checkout-e2e probe fails; PagerDuty alert "
          "P1-CHECKOUT-DOWN fires to the on-call SRE."],
         ["06:14", "M. Dubois", "On-call acknowledges. Confirms 502s in eu-central-1 "
          "and eu-west-1."],
         ["06:19", "M. Dubois", "Incident declared SEV-1. Bridge opened. "
          "S. Hartmann takes incident command."],
         ["06:23", "S. Hartmann", "Gateway logs show <font face='Courier'>x509: "
          "certificate has expired or is not yet valid</font>. Cause identified "
          "11 minutes after detection."],
         ["06:31", "L. Reber", "Status page updated; support scripted response "
          "published."],
         ["06:38", "M. Dubois", "Renewed certificate located in Vault. Change freeze "
          "exception requested from the duty manager."],
         ["06:51", "Duty manager", "Freeze exception granted."],
         ["06:57", "M. Dubois", "Certificate installed on lb-acq-01/02 in "
          "eu-central-1; configuration reloaded. Success rate recovers to 71%."],
         ["07:04", "M. Dubois", "eu-west-1 reloaded. Success rate returns to "
          "baseline. Incident mitigated."],
         ["07:40", "S. Hartmann", "30 minutes of clean metrics observed. Incident "
          "closed; status page cleared."],
         ["2026-07-30 14:00", "Payments guild", "Postmortem review held. Actions "
          "agreed and raised in Jira."]],
        [24 * mm, 24 * mm, W - 48 * mm], cell_style=COMPACT))

    s.append(P("4. Root cause", H2))
    s.append(panel([P(
        "<b>Root cause.</b> Certificate renewal and certificate deployment were two "
        "separate processes, and only the first was automated. cert-manager issued "
        "the replacement certificate into Vault on 12 July, but nothing consumed it: "
        "the load balancers read their certificate from a file baked into the "
        "configuration bundle, which is only rewritten by a Terraform apply. No "
        "apply ran between 12 July and the expiry, so the expired certificate stayed "
        "in place. The 30-day expiry alert that should have caught this had been "
        "routed to a Slack channel that was archived in May 2026, so no human ever "
        "saw it.", BODY)], W))
    s.append(Spacer(1, 4))
    s.append(P("Five whys", H2_PLAIN))
    s.extend(bullets([
        "Checkout returned 502 &mdash; the gateway could not establish TLS to the "
        "acquirer load balancer.",
        "The load balancer presented an expired certificate.",
        "The renewed certificate existed in Vault but had never been deployed.",
        "Deployment of a renewed certificate requires a Terraform apply that nobody "
        "runs on a schedule.",
        "The expiry warning that would have prompted that apply was delivered to an "
        "archived Slack channel and was never seen.",
    ], BODY, bullet="&rarr;"))

    s.append(P("5. Contributing factors", H2))
    s.extend(bullets([
        "The quarter-end change freeze added 13 minutes to recovery while an "
        "exception was obtained. The freeze policy did not carve out incident "
        "mitigation.",
        "Certificate inventory lived in a spreadsheet last updated in March 2026; "
        "lb-acq-01/02 were not on it.",
        "No pre-expiry synthetic check existed. Detection was by customer-facing "
        "failure, not by an early warning.",
    ]))

    s.append(P("6. What went well", H2))
    s.extend(bullets([
        "Detection was automated and immediate: 2 seconds from expiry to alert.",
        "Diagnosis took 11 minutes from acknowledgement, because gateway TLS errors "
        "are logged verbatim rather than collapsed into a generic 502.",
        "Customer communication went out at 06:31, within the 30-minute commitment.",
    ]))

    s.append(P("7. Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Type", "Owner", "Due", "Status"],
        [["OPS-3312", "Build an automated certificate inventory from live TLS "
          "endpoints, refreshed daily, replacing the spreadsheet.", "Prevent",
          "M. Dubois", "2026-08-15", "Done"],
         ["OPS-3313", "Make the load balancers read certificates from Vault at "
          "reload time so that renewal and deployment are one step.", "Prevent",
          "M. Dubois", "2026-08-29", "Done"],
         ["OPS-3314", "Re-route all certificate expiry alerts to the SRE PagerDuty "
          "service; add an ownership check that fails if the destination channel "
          "is archived.", "Detect", "S. Hartmann", "2026-08-08", "Done"],
         ["OPS-3315", "Add a synthetic probe that fails when any production "
          "certificate is within 21 days of expiry.", "Detect", "A. Novak",
          "2026-08-14", "Done"],
         ["PAY-1190", "Return a specific, retryable error to checkout-web on "
          "acquirer TLS failure instead of a bare 502.", "Mitigate", "T. Iversen",
          "2026-08-19", "Done"],
         ["GOV-221", "Amend the change freeze policy to exempt changes made under "
          "an open SEV-1 or SEV-2 incident.", "Process", "R. Bianchi", "2026-08-19",
          "Done"]],
        [17 * mm, W - 84 * mm, 15 * mm, 20 * mm, 18 * mm, 14 * mm],
        cell_style=COMPACT))
    s.append(Spacer(1, 4))
    s.append(P("Sign-off: R. Bianchi (Head of Platform), 2026-08-05. All six actions "
               "verified complete on 2026-08-19.", SMALL))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ================================================== 02 - engineering, mono ==

def doc_02():
    path = OUT / "INC-5102-orders-api-oom-postmortem.pdf"
    W = A4[0] - 36 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont("Courier", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, A4[1] - 12 * mm,
                          "platform-eng/postmortems/2026/INC-5102.md")
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 12 * mm,
                               "rendered 2026-08-06 09:14 UTC")
        canvas.setStrokeColor(RULE)
        canvas.line(18 * mm, A4[1] - 14 * mm, A4[0] - 18 * mm, A4[1] - 14 * mm)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, "- %d -" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=17 * mm,
                            bottomMargin=13 * mm, leftMargin=18 * mm,
                            rightMargin=18 * mm,
                            title="INC-5102 orders-api OOM postmortem",
                            author="k.oyelaran")

    rule = "=" * 92
    thin = "-" * 92
    s = []
    s.append(P(rule, MONO_S))
    s.append(P("POSTMORTEM  INC-5102", ParagraphStyle(
        "t", parent=MONO, fontName="Courier-Bold", fontSize=13, leading=16)))
    s.append(P("orders-api pods OOMKilled under retry storm; order submission "
               "degraded 3h47m", MONO))
    s.append(P(rule, MONO_S))
    s.append(Spacer(1, 4))
    s.append(P(
        "jira        : INC-5102  (postmortem PLAT-884; actions PLAT-885..889)<br/>"
        "severity    : SEV-2<br/>"
        "environment : production / cluster eks-prod-eu-1 / namespace orders<br/>"
        "component   : orders-api v2026.7.3, redis-orders 7.2, kong-gw 3.4<br/>"
        "opened      : 2026-08-03 14:22 UTC<br/>"
        "mitigated   : 2026-08-03 16:41 UTC<br/>"
        "closed      : 2026-08-03 18:09 UTC<br/>"
        "author      : k.oyelaran<br/>"
        "reviewers   : d.fischer, p.almeida, s.hartmann<br/>"
        "status      : closed, all actions shipped", MONO))
    s.append(Spacer(1, 4))

    s.append(P(thin, MONO_S))
    s.append(P("## 1. SUMMARY", ParagraphStyle("h", parent=MONO,
                                               fontName="Courier-Bold", fontSize=9.5)))
    s.append(P(thin, MONO_S))
    s.append(P(
        "Between 14:22 and 18:09 UTC on 3 August 2026, order submission through "
        "orders-api failed intermittently, peaking at 34% of POST /v2/orders "
        "returning 503. Pods in the orders-api deployment were killed by the kernel "
        "OOM killer in a repeating cycle: a pod would accumulate heap until it hit "
        "its 1.5 GiB memory limit, be killed, and its in-flight requests would be "
        "retried onto the remaining pods, accelerating their own growth. 96 pod "
        "restarts were recorded in the window against a baseline of zero.", BODY))
    s.append(P(
        "Read paths (GET /v2/orders, order history, tracking) were unaffected "
        "because they are served by a separate deployment. No orders were lost: "
        "every rejected submission returned 503 with a client-visible retry hint, "
        "and the idempotency key store prevented duplicates on retry.", BODY))

    s.append(P(thin, MONO_S))
    s.append(P("## 2. IMPACT", ParagraphStyle("h2", parent=MONO,
                                              fontName="Courier-Bold", fontSize=9.5)))
    s.append(P(thin, MONO_S))
    s.append(P(
        "failed submissions      : 21,904 of 64,410 attempts (34.0% peak, 12.1% mean)<br/>"
        "customers affected      : ~8,100 unique accounts<br/>"
        "orders permanently lost : 0 (all retried successfully within 15 min)<br/>"
        "revenue at risk         : CHF 1.29m in basket value, none confirmed lost<br/>"
        "slo burn                : 41% of the monthly error budget for orders-api<br/>"
        "support tickets         : 212", MONO_S))
    s.append(Spacer(1, 5))
    s.append(bar_chart(
        [[0, 0, 0, 1, 38, 41, 16, 0, 0]],
        ["12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00",
         "20:00"],
        width=W, height=38 * mm, colours=(RED,), y_max=50, y_step=10,
        title="orders-api pod restarts per hour, 2026-08-03 UTC"))
    s.append(P("Figure 1 &mdash; restarts per hour. Baseline for this deployment is "
               "zero restarts per day.", CAPTION))
    s.append(Spacer(1, 3))
    s.append(line_chart(
        [[410, 430, 445, 610, 980, 1320, 1480, 1495, 720, 430],
         [400, 402, 405, 408, 410, 415, 412, 409, 405, 402]],
        ["13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
         "17:00", "18:00"],
        width=W, height=40 * mm, colours=(AMBER, TEAL), y_min=0, y_max=1600,
        y_step=400,
        title="Heap in use, MiB - affected pod (orange) vs control pod (teal)"))
    s.append(P("Figure 2 &mdash; the affected pod's heap grows monotonically to the "
               "1,536 MiB limit. The control pod, serving the same traffic with the "
               "cache disabled, is flat.", CAPTION))

    s.append(P(thin, MONO_S))
    s.append(P("## 3. TIMELINE (UTC)", ParagraphStyle("h3", parent=MONO,
                                                      fontName="Courier-Bold",
                                                      fontSize=9.5)))
    s.append(P(thin, MONO_S))
    s.append(P(
        "2026-07-30 11:05  orders-api v2026.7.3 released. Ships a new in-process<br/>"
        "                  response cache for the pricing lookup (PR #4412).<br/>"
        "2026-08-03 09:00  Weekend promo campaign begins; submission volume ~2.4x<br/>"
        "                  the weekday baseline.<br/>"
        "2026-08-03 14:22  First OOMKill on orders-api-7c9d4. Alert<br/>"
        "                  ORDERS-POD-RESTART fires (threshold: >2 restarts/10m).<br/>"
        "2026-08-03 14:25  k.oyelaran acknowledges. Dashboards show heap climbing<br/>"
        "                  linearly on every pod since the 30 July release.<br/>"
        "2026-08-03 14:40  Declared SEV-2. p.almeida joins as ops.<br/>"
        "2026-08-03 14:58  Memory limit raised 1.5 -> 3.0 GiB as a holding action.<br/>"
        "                  This slows the cycle but does not stop it.<br/>"
        "2026-08-03 15:20  Heap dump captured from orders-api-7c9d4 and analysed.<br/>"
        "                  90% of live objects are PricingCacheEntry.<br/>"
        "2026-08-03 15:44  Cause confirmed: the cache is unbounded and keyed by a<br/>"
        "                  value that includes the request id, so it never hits.<br/>"
        "2026-08-03 16:05  Change PLAT-884-hotfix approved: disable the cache via<br/>"
        "                  the PRICING_CACHE_ENABLED feature flag.<br/>"
        "2026-08-03 16:41  Flag flipped to false; rolling restart completed.<br/>"
        "                  Error rate returns to baseline. Incident mitigated.<br/>"
        "2026-08-03 18:09  90 minutes of flat heap observed on all pods.<br/>"
        "                  Incident closed.<br/>"
        "2026-08-05 10:00  Postmortem review with platform-eng and payments.",
        TIGHT_MONO))

    s.append(P(thin, MONO_S))
    s.append(P("## 4. ROOT CAUSE", ParagraphStyle("h4", parent=MONO,
                                                  fontName="Courier-Bold",
                                                  fontSize=9.5)))
    s.append(P(thin, MONO_S))
    s.append(P(
        "The pricing response cache added in PR #4412 was constructed with an "
        "unbounded <font face='Courier'>HashMap</font> and its key was built from "
        "the full request context object, whose <font face='Courier'>toString()</font> "
        "includes the per-request correlation id. Every request therefore produced a "
        "unique key: the cache never returned a hit and never evicted an entry. It "
        "was, in effect, a memory leak with a cache-shaped API. Under normal weekday "
        "volume a pod reached its 1.5 GiB limit in roughly 40 hours, which is longer "
        "than the deployment's usual lifetime, so the leak was invisible in the four "
        "days between release and incident. The promo campaign on 3 August tripled "
        "request volume and cut that time to about five hours, at which point all "
        "pods began hitting the limit together.", BODY))
    s.append(P(
        "The retry storm that turned a rolling restart into a 34% failure rate is a "
        "second-order effect: kong-gw retried 503s up to three times with no jitter, "
        "so each OOMKill produced a synchronised burst of retries onto the surviving "
        "pods.", BODY))

    s.append(P(thin, MONO_S))
    s.append(P("## 5. ACTION PLAN", ParagraphStyle("h5", parent=MONO,
                                                   fontName="Courier-Bold",
                                                   fontSize=9.5)))
    s.append(P(thin, MONO_S))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["PLAT-885", "Replace the pricing cache with a bounded Caffeine cache "
          "(max 50k entries, 10 min TTL) keyed by sku+currency+tier only.",
          "k.oyelaran", "2026-08-10", "Done"],
         ["PLAT-886", "Add a soak stage to the release pipeline: 60 minutes at 3x "
          "peak traffic, failing the release if RSS grows more than 5%.",
          "d.fischer", "2026-08-24", "Done"],
         ["PLAT-887", "Alert on heap growth trend (>10%/hour sustained for 2 hours) "
          "rather than only on restarts, so the leak is caught before the kill.",
          "p.almeida", "2026-08-17", "Done"],
         ["PLAT-888", "Add jittered exponential backoff to kong-gw retries and cap "
          "retry budget at 10% of request volume.", "p.almeida", "2026-08-21",
          "Done"],
         ["PLAT-889", "Require a cache-design note (bound, eviction, key, expected "
          "hit rate) in the PR template for any new in-process cache.",
          "d.fischer", "2026-08-14", "Done"]],
        [19 * mm, W - 79 * mm, 21 * mm, 20 * mm, 15 * mm],
        head_bg=colors.HexColor("#333333"), cell_style=MONO_S, zebra=False))
    s.append(Spacer(1, 4))
    s.append(P("## 6. LESSONS", ParagraphStyle("h6", parent=MONO,
                                               fontName="Courier-Bold", fontSize=9.5)))
    s.append(P(
        "- A cache with a 0% hit rate is indistinguishable from a leak, and nothing "
        "in our metrics reported cache hit rate.<br/>"
        "- Raising the memory limit bought time but hid the signal; we should have "
        "taken the heap dump first.<br/>"
        "- Load tests run at 1x peak for 10 minutes. Neither the duration nor the "
        "multiple would have surfaced this.", MONO_S))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ==================================================== 03 - wiki page export ==

def doc_03():
    path = OUT / "INC-4977-postgres-wal-disk-full.pdf"
    W = A4[0] - 40 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#F4F5F7"))
        canvas.rect(0, A4[1] - 16 * mm, A4[0], 16 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#5E6C84"))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(20 * mm, A4[1] - 10 * mm,
                          "Spaces  /  Site Reliability  /  Postmortems  /  2026  /  "
                          "INC-4977")
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 10 * mm,
                               "Exported from Confluence  ·  2026-08-11")
        canvas.setStrokeColor(colors.HexColor("#DFE1E6"))
        canvas.line(0, A4[1] - 16 * mm, A4[0], A4[1] - 16 * mm)
        canvas.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(20 * mm, 10 * mm,
                          "INC-4977 - Primary database read-only for 26 minutes "
                          "(WAL exhaustion)")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, "%d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=22 * mm,
                            bottomMargin=18 * mm, leftMargin=20 * mm,
                            rightMargin=20 * mm,
                            title="INC-4977 - Primary database WAL exhaustion",
                            author="a.novak")
    s = []
    s.append(P("INC-4977 &mdash; Primary database went read-only for 26 minutes "
               "(WAL exhaustion)", H1))
    s.append(P("Created by <b>A. Novak</b> on 2026-06-19 &middot; last modified by "
               "<b>D. Fischer</b> on 2026-07-02 &middot; 14 comments", SMALL))
    lab = Table([[P("<b>postmortem</b>", SMALL), P("<b>sev-1</b>", SMALL),
                  P("<b>database</b>", SMALL), P("<b>completed</b>", SMALL)]],
                colWidths=[24 * mm] * 4, hAlign="LEFT")
    lab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#DFE1E6")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#C1C7D0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    s.append(Spacer(1, 3))
    s.append(lab)
    s.append(Spacer(1, 6))
    s.append(panel([
        P("<b>At a glance.</b> On 18 June 2026 the primary Postgres instance for the "
          "customer database filled its write-ahead log volume and refused all "
          "writes for 26 minutes. The trigger was a replication slot left behind by "
          "a decommissioned reporting replica, which held WAL segments that could "
          "never be recycled. Reads were unaffected throughout. No data was lost.",
          BODY_S)], W))
    s.append(P("Incident record", H2))
    s.append(kv_table([
        ("Jira issue", "INC-4977"),
        ("Related issues", "DBA-772, DBA-773, DBA-774, DBA-775, OPS-3290"),
        ("Severity", "SEV-1 (writes unavailable to a tier-1 service)"),
        ("Environment", "Production &mdash; pg-cust-prod-01 (primary), "
                        "pg-cust-prod-02 (standby), PostgreSQL 15.6"),
        ("Detected at", "2026-06-18 21:47 CEST"),
        ("Mitigated at", "2026-06-18 22:13 CEST"),
        ("Duration", "26 minutes"),
        ("Incident commander", "A. Novak"),
        ("Participants", "A. Novak (DBA), D. Fischer (SRE), M. Dubois (on-call), "
                         "R. Bianchi (duty manager)"),
        ("Review date", "2026-06-24"),
        ("Status", "Closed"),
    ], W, label_bg=colors.HexColor("#F4F5F7")))

    s.append(P("Description", H2))
    s.append(P(
        "At 21:47 CEST on 18 June 2026, every write to the customer database began "
        "failing with <font face='Courier'>PANIC: could not write to file "
        "pg_wal/xlogtemp.2891: No space left on device</font>. PostgreSQL shut down "
        "the write path and the instance came back up refusing writes. Registration, "
        "profile updates, consent changes and order writes all failed for 26 minutes. "
        "Read traffic continued to be served normally from the standby and from the "
        "primary itself.", BODY))
    s.append(P(
        "The <font face='Courier'>pg_wal</font> volume, provisioned at 200 GiB "
        "against a normal steady state of 8&ndash;12 GiB, had been growing since "
        "26 May. It crossed 95% at 20:31 and filled at 21:47.", BODY))

    s.append(Spacer(1, 4))
    s.append(line_chart(
        [[9, 11, 24, 47, 68, 86, 104, 129, 151, 173, 191, 200]],
        ["26 May", "29 May", "1 Jun", "4 Jun", "7 Jun", "10 Jun", "13 Jun",
         "15 Jun", "16 Jun", "17 Jun", "18 Jun", "18 Jun 21:47"],
        width=W, height=46 * mm, colours=(AMBER,), y_min=0, y_max=200, y_step=50,
        title="pg_wal volume usage, GiB (capacity 200 GiB)"))
    s.append(P("Figure 1 &mdash; WAL retained from 26 May, the day the reporting "
               "replica was decommissioned. Growth is roughly linear at 8 GiB/day.",
               CAPTION))

    s.append(P("Timeline", H2))
    s.append(grid_table(
        ["When (CEST)", "What happened"],
        [["2026-05-26 16:20", "Reporting replica pg-cust-rep-03 is decommissioned "
          "as part of DBA-701. The VM is deleted. The replication slot "
          "<font face='Courier'>rep_03_slot</font> is not dropped on the primary."],
         ["2026-05-26 onward", "The orphaned slot pins WAL. pg_wal begins growing at "
          "roughly 8 GiB per day."],
         ["2026-06-14 03:00", "Disk usage crosses 70%. The warning alert fires into "
          "the #dba-noise channel, which has notifications muted. Nobody reads it."],
         ["2026-06-18 20:31", "Usage crosses 95%. The critical alert fires but is "
          "configured as a low-urgency notification and does not page."],
         ["2026-06-18 21:47", "pg_wal reaches 200 GiB. The primary panics and "
          "restarts read-only. Application write errors trigger "
          "CUST-DB-WRITE-FAIL, which does page."],
         ["2026-06-18 21:49", "M. Dubois acknowledges and escalates to the DBA "
          "on-call."],
         ["2026-06-18 21:53", "A. Novak joins, declares SEV-1, takes command."],
         ["2026-06-18 21:58", "<font face='Courier'>pg_replication_slots</font> "
          "shows rep_03_slot inactive with 191 GiB of retained WAL. Cause "
          "identified."],
         ["2026-06-18 22:04", "Decision recorded on the bridge: drop the slot rather "
          "than extend the volume, because the replica no longer exists."],
         ["2026-06-18 22:09", "<font face='Courier'>SELECT "
          "pg_drop_replication_slot('rep_03_slot');</font> executed. WAL recycling "
          "resumes; usage falls to 12 GiB within 90 seconds."],
         ["2026-06-18 22:13", "Writes accepted again. Incident mitigated."],
         ["2026-06-18 22:45", "Queued application retries drained. Incident closed."],
         ["2026-06-24 11:00", "Postmortem review held with DBA, SRE and the customer "
          "platform team."]],
        [26 * mm, W - 26 * mm], head_bg=colors.HexColor("#0052CC")))

    s.append(P("Root cause", H2))
    s.append(P(
        "<b>Decommissioning a streaming replica did not include dropping its "
        "replication slot on the primary.</b> An inactive slot instructs PostgreSQL "
        "to retain every WAL segment the (now non-existent) consumer has not "
        "confirmed, indefinitely. WAL therefore accumulated at the rate the database "
        "generated it, roughly 8 GiB/day, until the volume was full. The runbook for "
        "replica decommissioning, last revised in 2023, listed nine steps and did "
        "not mention slots.", BODY))
    s.append(P(
        "Two independent alerts would have caught the growth with days to spare. "
        "Both failed for routing reasons rather than for lack of a signal: the 70% "
        "warning went to a muted channel, and the 95% critical was classified "
        "low-urgency and did not page.", BODY))

    s.append(P("Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["DBA-772", "Add 'drop the replication slot on the primary and verify it is "
          "gone' as a mandatory, checked step in the replica decommissioning "
          "runbook.", "A. Novak", "2026-06-26", "Done"],
         ["DBA-773", "Alert on any replication slot that is inactive for more than "
          "one hour, or that retains more than 20 GiB, paging the DBA on-call.",
          "A. Novak", "2026-07-03", "Done"],
         ["DBA-774", "Re-classify pg_wal usage above 90% as a paging alert and route "
          "it to the DBA PagerDuty service.", "D. Fischer", "2026-06-30", "Done"],
         ["DBA-775", "Audit all production clusters for orphaned slots and remove "
          "them. Three further orphans were found on pg-billing-prod-01 and "
          "removed.", "A. Novak", "2026-07-10", "Done"],
         ["OPS-3290", "Review every alert routed to #dba-noise; delete or re-route. "
          "Muted channels are no longer a permitted alert destination.",
          "D. Fischer", "2026-07-17", "Done"]],
        [19 * mm, W - 79 * mm, 21 * mm, 20 * mm, 15 * mm],
        head_bg=colors.HexColor("#0052CC")))
    s.append(Spacer(1, 5))
    s.append(P("<b>Follow-up.</b> The three orphaned slots found under DBA-775 had "
               "been retaining 4 GiB and 11 GiB respectively; neither cluster was "
               "close to exhaustion. All five actions were verified complete at the "
               "2026-07-22 reliability review.", BODY_S))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ======================================================== 04 - two columns ==

def doc_04():
    path = OUT / "INC-5230-dns-cutover-eu-west-outage.pdf"
    M = 15 * mm
    colw = (A4[0] - 2 * M - 8 * mm) / 2
    full = A4[0] - 2 * M

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(2)
        canvas.line(M, A4[1] - 12 * mm, A4[0] - M, A4[1] - 12 * mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(M, A4[1] - 10 * mm, "HELVETICA RETAIL AG  ·  "
                                              "INFRASTRUCTURE")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        canvas.drawRightString(A4[0] - M, A4[1] - 10 * mm,
                               "Postmortem INC-5230  ·  page %d of 2" % doc.page)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(M, 9 * mm, "Confidential - internal distribution only")
        canvas.drawRightString(A4[0] - M, 9 * mm, "Approved 2026-08-12 by J. Keller")
        canvas.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=M, rightMargin=M,
                          topMargin=16 * mm, bottomMargin=14 * mm,
                          title="INC-5230 DNS cutover outage postmortem",
                          author="t.iversen")
    head_h = 92 * mm
    body_top = A4[1] - doc.topMargin - head_h
    head_frame = Frame(M, body_top, full, head_h, id="head",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    c1 = Frame(M, doc.bottomMargin, colw, body_top - doc.bottomMargin, id="c1",
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    c2 = Frame(M + colw + 8 * mm, doc.bottomMargin, colw,
               body_top - doc.bottomMargin, id="c2",
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    fh = A4[1] - doc.topMargin - doc.bottomMargin
    l1 = Frame(M, doc.bottomMargin, colw, fh, id="l1", leftPadding=0, rightPadding=0,
               topPadding=0, bottomPadding=0)
    l2 = Frame(M + colw + 8 * mm, doc.bottomMargin, colw, fh, id="l2", leftPadding=0,
               rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="first", frames=[head_frame, c1, c2], onPage=decorate),
        PageTemplate(id="later", frames=[l1, l2], onPage=decorate),
    ])

    s = []
    s.append(P("Partial loss of eu-west storefront during CDN cutover", H1))
    s.append(P("Postmortem for INC-5230 &middot; 42 minutes &middot; SEV-2 &middot; "
               "author T. Iversen (Network Engineering) &middot; reviewed "
               "2026-08-11", SMALL))
    s.append(Spacer(1, 4))
    s.append(kv_table([
        ("Jira issue", "INC-5230 &nbsp;&middot;&nbsp; actions NET-1441 to NET-1445"),
        ("Severity / status", "SEV-2 &middot; Closed 2026-08-12"),
        ("Window", "2026-08-06 02:14 &ndash; 02:56 UTC (42 minutes)"),
        ("Blast radius", "eu-west-1 storefront only; 18% of global traffic"),
        ("Environment / service", "Production &middot; edge-cdn, storefront-web, "
                                  "ns1/ns2.helvetica.internal"),
        ("Commander / comms", "T. Iversen &middot; L. Reber"),
    ], full, label_w=38 * mm))
    s.append(Spacer(1, 3))
    s.append(request_path_diagram(width=full, height=40 * mm, fail_index=2))
    s.append(FrameBreak())

    s.append(P("1. Description", H2))
    s.append(P(
        "During a planned migration of the European storefront from the legacy CDN "
        "to edge-cdn, the DNS records for "
        "<font face='Courier'>www.helvetica-retail.eu</font> were repointed at "
        "02:14 UTC on 6 August 2026. The new CNAME target was published with a "
        "trailing-dot error in the zone file, producing the fully qualified name "
        "<font face='Courier'>eu.edge-cdn.net.helvetica.internal</font> instead of "
        "<font face='Courier'>eu.edge-cdn.net</font>. That name does not exist, so "
        "every resolver that picked up the new record answered NXDOMAIN.", BODY))
    s.append(P(
        "Customers in eu-west-1 whose resolver cache had expired could not reach the "
        "storefront at all: the browser reported a DNS failure rather than an error "
        "page, so the failure was invisible to our own HTTP monitoring. Customers "
        "with a warm cache were unaffected until their TTL expired, which is why the "
        "impact ramped up over the first fifteen minutes rather than starting at "
        "100%.", BODY))

    s.append(P("2. Impact", H2))
    s.extend(bullets([
        "42 minutes of partial unavailability, ramping from 0% to an estimated 78% "
        "of eu-west-1 sessions.",
        "Approximately 34,000 sessions unable to resolve the storefront.",
        "CHF 96,400 of estimated deferred revenue; CHF 11,300 assessed as lost.",
        "No impact to eu-central, us-east or ap-south, which were not part of this "
        "cutover wave.",
        "No data loss, no security impact.",
    ], BODY_S))
    s.append(Spacer(1, 3))
    s.append(bar_chart(
        [[0.2, 0.3, 0.2, 0.4], [78.0, 0.3, 0.2, 0.5]],
        ["eu-west-1", "eu-central-1", "us-east-1", "ap-south-1"],
        width=colw, height=40 * mm, colours=(STEEL, RED), y_max=100, y_step=25,
        title="Failed page loads, % by region",
        series_names=["before", "during"]))
    s.append(P("Figure 2 &mdash; only the cutover region is affected.", CAPTION))

    s.append(P("3. Timeline (UTC)", H2))
    s.append(grid_table(
        ["Time", "Event"],
        [["01:50", "Change NET-CHG-8871 opened. Pre-checks pass."],
         ["02:14", "Zone file applied to ns1/ns2. TTL is 300s."],
         ["02:16", "Automated post-change check passes &mdash; it queries the "
          "storefront through the corporate resolver, whose cache is still warm."],
         ["02:21", "First customer report via the eu support queue."],
         ["02:29", "Second and third reports. L. Reber escalates to the change "
          "engineer."],
         ["02:31", "T. Iversen declares SEV-2. Synthetic checks from an external "
          "vantage point confirm NXDOMAIN."],
         ["02:38", "Zone file diff reviewed on the bridge; the trailing dot is "
          "spotted."],
         ["02:44", "Corrected zone published; serial incremented."],
         ["02:49", "Resolvers begin returning the correct answer as the 300s TTL "
          "expires."],
         ["02:56", "External checks green from all five vantage points. Mitigated."],
         ["03:30", "Cutover re-attempted successfully with the corrected record."],
         ["2026-08-11", "Postmortem review held."]],
        [14 * mm, colw - 14 * mm], cell_style=ParagraphStyle(
            "tiny", parent=BODY_S, fontSize=7, leading=9)))

    s.append(P("4. Root cause", H2))
    s.append(P(
        "<b>A missing trailing dot in a hand-edited BIND zone file caused the CNAME "
        "target to be interpreted as relative to the zone origin.</b> "
        "<font face='Courier'>eu.edge-cdn.net</font> without a terminating dot is "
        "expanded to <font face='Courier'>eu.edge-cdn.net.helvetica.internal</font>, "
        "a name that has never existed. The zone file passed "
        "<font face='Courier'>named-checkzone</font>, which validates syntax and "
        "cannot know that the operator meant an absolute name.", BODY_S))
    s.append(P(
        "The error survived to production because the post-change verification "
        "queried the internal corporate resolver, which still held the previous "
        "answer in cache. A check from outside the network would have failed "
        "immediately.", BODY_S))

    s.append(P("5. Contributing factors", H2))
    s.extend(bullets([
        "Zone files are edited by hand and applied directly; there is no diff review "
        "step for DNS changes, unlike every other production change.",
        "The change was scheduled at 02:14 local, when a single engineer was on "
        "duty and no reviewer was available.",
        "HTTP monitoring cannot see a DNS failure, and we had no DNS-resolution "
        "monitoring from outside the corporate network.",
    ], BODY_S))

    s.append(P("6. Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["NET-1441", "Move all production zones into version control with mandatory "
          "peer review before apply.", "T. Iversen", "2026-09-04", "Done"],
         ["NET-1442", "Add a CI check that rejects any CNAME or MX target which is "
          "not fully qualified with a trailing dot.", "T. Iversen", "2026-08-21",
          "Done"],
         ["NET-1443", "Add external DNS resolution probes from five public vantage "
          "points, alerting on NXDOMAIN or a changed answer.", "A. Novak",
          "2026-08-28", "Done"],
         ["NET-1444", "Post-change verification must run from an external vantage "
          "point with a cold cache; update the change template accordingly.",
          "L. Reber", "2026-08-19", "Done"],
         ["NET-1445", "Lower TTL to 60s for the 24 hours preceding any planned DNS "
          "cutover, and restore it afterwards.", "T. Iversen", "2026-08-26",
          "Done"]],
        [17 * mm, colw - 68 * mm, 19 * mm, 18 * mm, 14 * mm],
        cell_style=ParagraphStyle("tiny2", parent=BODY_S, fontSize=7, leading=9)))
    s.append(Spacer(1, 4))
    s.append(P("<b>What went well.</b> Once escalated, the diagnosis took seven "
               "minutes and the fix was a two-line change. The rollback plan for the "
               "cutover was written and tested in advance, and was ready to use had "
               "the corrected record not worked.", BODY_S))

    story = [NextPageTemplate("later")] + s
    doc.build(story)
    return path


# ================================================= 05 - landscape one-pager ==

def doc_05():
    path = OUT / "INC-5044-kafka-consumer-stall-onepager.pdf"
    PS = landscape(A4)
    M = 12 * mm
    W = PS[0] - 2 * M

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(TEAL)
        canvas.rect(0, PS[1] - 16 * mm, PS[0], 16 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(M, PS[1] - 10.5 * mm,
                          "INCIDENT ONE-PAGER  ·  INC-5044")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(PS[0] - M, PS[1] - 10.5 * mm,
                               "Order events pipeline stalled 2h11m  ·  SEV-2  "
                               "·  closed")
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(M, 7 * mm, "Streaming Platform team  ·  author "
                                     "p.almeida  ·  reviewed 2026-07-16  ·  "
                                     "distribution: engineering, ops, customer care")
        canvas.drawRightString(PS[0] - M, 7 * mm, "1 / 1")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=PS, topMargin=19 * mm,
                            bottomMargin=11 * mm, leftMargin=M, rightMargin=M,
                            title="INC-5044 one-pager", author="p.almeida")
    s = []
    s.append(tiles([
        ("Duration", "2h 11m", "13:04 - 15:15 UTC, 2026-07-09"),
        ("Events delayed", "1.84 M", "peak consumer lag 1,842,000"),
        ("Events lost", "0", "all replayed from the log"),
        ("Customers affected", "~24,000", "delayed confirmation email"),
        ("Jira", "INC-5044", "actions STR-902 to STR-906"),
    ], W))
    s.append(Spacer(1, 5))

    left = []
    left.append(P("Description", H2))
    left.append(P(
        "On 9 July 2026 the <font face='Courier'>order-events</font> consumer group "
        "stopped making progress at 13:04 UTC. Producers continued to write "
        "normally, so no events were lost, but every downstream effect of an order "
        "&mdash; confirmation email, warehouse pick request, loyalty accrual, "
        "fraud scoring &mdash; was delayed by up to 2 hours 11 minutes. Consumer lag "
        "grew steadily to 1.84 million events before recovery. Order placement "
        "itself, which is synchronous, was never affected: customers could check out "
        "normally and saw nothing wrong until their confirmation email failed to "
        "arrive.", BODY_S))
    left.append(P("Root cause", H2))
    left.append(panel([P(
        "The 8 July upgrade of the Kafka client library from 3.4.1 to 3.7.0 changed "
        "the default <font face='Courier'>max.poll.interval.ms</font> from 300,000 "
        "to 60,000 ms. The enrichment step in this consumer routinely takes 70&ndash;"
        "90 seconds per batch when the pricing service is slow. Under the new "
        "default, the broker judged the consumer dead mid-batch and triggered a "
        "rebalance; the rebalance revoked the partitions the consumer was still "
        "working on, which caused the next poll to fail and start another rebalance. "
        "The group entered a continuous rebalance loop and committed no offsets for "
        "two hours.", BODY_S)], W * 0.49, bg=colors.HexColor("#E8F4F4"), bar=TEAL))
    left.append(Spacer(1, 3))
    left.append(P("The upgrade was a transitive bump: the application pinned an "
                  "internal SDK, and the SDK's minor release moved the Kafka client. "
                  "No release note in our own changelog mentioned it.", BODY_S))
    left.append(P("Timeline (UTC)", H2))
    left.append(grid_table(
        ["Time", "Event"],
        [["07-08 16:20", "internal-sdk 9.4.0 deployed; pulls kafka-clients 3.7.0."],
         ["07-09 13:04", "First rebalance. Offset commits stop."],
         ["13:19", "Lag alert fires at 100k events (warning, no page)."],
         ["13:52", "Lag crosses 500k. Paging alert fires. p.almeida acknowledges."],
         ["14:05", "SEV-2 declared. Rebalance loop visible in the group coordinator "
          "log."],
         ["14:31", "Diff of the SDK bump reviewed; the changed default is found."],
         ["14:48", "max.poll.interval.ms pinned to 300000 in the consumer config; "
          "change approved."],
         ["15:02", "Rolling restart of the consumer group begins."],
         ["15:15", "Group stable, offsets committing, lag draining at 42k events/min."],
         ["16:03", "Lag back to zero. Incident closed."],
         ["07-16", "Postmortem review."]],
        [17 * mm, W * 0.49 - 17 * mm], head_bg=TEAL,
        cell_style=ParagraphStyle("t5", parent=BODY_S, fontSize=7, leading=9)))

    right = []
    right.append(line_chart(
        [[0, 120, 410, 780, 1180, 1560, 1842, 1500, 700, 0]],
        ["13:00", "13:20", "13:40", "14:00", "14:20", "14:40", "15:15", "15:30",
         "15:45", "16:03"],
        width=W * 0.49, height=44 * mm, colours=(RED,), y_min=0, y_max=2000,
        y_step=500, title="Consumer lag, thousands of events"))
    right.append(P("Figure 1 &mdash; lag peaks at mitigation and drains in 48 "
                   "minutes.", CAPTION))
    right.append(Spacer(1, 2))
    right.append(pie_chart(
        [58, 21, 13, 8],
        ["confirmation email", "warehouse pick", "loyalty accrual", "fraud scoring"],
        width=W * 0.49, height=42 * mm,
        title="Delayed effects by downstream consumer, % of backlog"))
    right.append(P("Action plan", H2))
    right.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "St."],
        [["STR-902", "Pin every Kafka consumer tuning value explicitly in config; "
          "never rely on client defaults.", "p.almeida", "2026-07-22", "Done"],
         ["STR-903", "Fail the build when a transitive dependency changes a "
          "documented default; publish a diff of effective config on every "
          "release.", "d.fischer", "2026-08-05", "Done"],
         ["STR-904", "Page on consumer lag at 100k rather than warn, and alert "
          "separately on 'no offset commit for 5 minutes'.", "p.almeida",
          "2026-07-24", "Done"],
         ["STR-905", "Move enrichment off the poll thread so a slow pricing call "
          "cannot trigger a rebalance.", "k.oyelaran", "2026-08-19", "Done"],
         ["STR-906", "Add a rebalance-storm runbook with the three commands used "
          "here.", "p.almeida", "2026-07-20", "Done"]],
        [16 * mm, W * 0.49 - 66 * mm, 18 * mm, 18 * mm, 11 * mm], head_bg=TEAL,
        cell_style=ParagraphStyle("t6", parent=BODY_S, fontSize=7, leading=9)))

    lt = Table([[f] for f in left], colWidths=[W * 0.49])
    rt = Table([[f] for f in right], colWidths=[W * 0.49])
    for t in (lt, rt):
        t.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
    cols = Table([[lt, "", rt]], colWidths=[W * 0.49, W * 0.02, W * 0.49])
    cols.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    s.append(cols)
    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


ALL = [doc_01, doc_02, doc_03, doc_04, doc_05]
