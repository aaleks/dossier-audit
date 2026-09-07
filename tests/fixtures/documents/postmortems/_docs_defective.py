"""The five defective postmortems (fixtures 06-10).

Each carries exactly the defect recorded for it in specs/_fixtures.md, and is
otherwise a plausible document. The defects are:

  06  action plan holds a single, unowned, non-specific item
  07  no timeline anywhere in the document
  08  description is vague - it never says what broke or who was affected
  09  root cause is explicitly undetermined; only competing hypotheses
  10  several at once: no Jira ID, undated two-line timeline, no root cause
      section, action plan with no owners or dates

They exist so that a stage which claims "the action plan is present" can be
shown to be wrong, and so that abstention can be scored on real absences.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from _common import (
    AMBER, BODY, BODY_S, CAPTION, GREEN, GREY, H1, H2, H2_PLAIN, INK, LIGHT, MONO,
    MONO_S, NAVY, OUT, P, PANEL_BG, RED, RULE, SERIF, SERIF_H, SMALL, STEEL, TEAL,
    ParagraphStyle, bar_chart, bullets, dashboard_screenshot, grid_table, kv_table,
    line_chart, panel, pie_chart, tiles, wave_sparkline,
)


# ================================ 06 - complete except a one-item action plan =

def doc_06():
    path = OUT / "INC-5310-nightly-billing-batch-overrun.pdf"
    W = A4[0] - 44 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont("Times-Bold", 9)
        canvas.setFillColor(INK)
        canvas.drawCentredString(A4[0] / 2, A4[1] - 15 * mm,
                                 "MERIDIAN FINANCIAL SERVICES")
        canvas.setFont("Times-Italic", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawCentredString(A4[0] / 2, A4[1] - 19 * mm,
                                 "Internal memorandum - not for distribution "
                                 "outside the group")
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.7)
        canvas.line(22 * mm, A4[1] - 21 * mm, A4[0] - 22 * mm, A4[1] - 21 * mm)
        canvas.line(22 * mm, 16 * mm, A4[0] - 22 * mm, 16 * mm)
        canvas.setFont("Times-Roman", 7.5)
        canvas.drawString(22 * mm, 12 * mm, "INC-5310  ·  post-incident memorandum")
        canvas.drawRightString(A4[0] - 22 * mm, 12 * mm, "Page %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=26 * mm,
                            bottomMargin=20 * mm, leftMargin=22 * mm,
                            rightMargin=22 * mm,
                            title="INC-5310 nightly billing batch overrun",
                            author="c.eberhart")
    s = []
    s.append(P("POST-INCIDENT MEMORANDUM", ParagraphStyle(
        "memo", parent=SERIF_H, fontSize=13, leading=16, spaceBefore=0,
        alignment=1)))
    s.append(Spacer(1, 5))
    s.append(P("<b>To:</b> Billing Operations, Group Finance, IT Service "
               "Management<br/>"
               "<b>From:</b> C. Eberhart, Batch Operations<br/>"
               "<b>Date:</b> 2026-05-21<br/>"
               "<b>Subject:</b> INC-5310 &mdash; nightly billing batch overran its "
               "window on 2026-05-18, delaying 61,400 invoices by 4h 40m",
               SERIF))
    s.append(Spacer(1, 3))
    s.append(kv_table([
        ("Jira issue", "INC-5310"),
        ("Severity", "SEV-3 &mdash; delayed, not lost; no customer-facing outage"),
        ("Environment", "Production &mdash; batch cluster btc-prod, "
                        "billing-engine 8.2.1"),
        ("Occurred", "2026-05-18, batch window 22:00&ndash;04:00 CEST"),
        ("Completed", "2026-05-19 08:40 CEST (4h 40m past the window)"),
        ("Author", "C. Eberhart &middot; reviewed by the Billing Operations "
                   "forum on 2026-05-21"),
    ], W, s=ParagraphStyle("kv6", parent=SERIF, fontSize=8.5, leading=11,
                           spaceAfter=0)))

    s.append(P("1. What happened", SERIF_H))
    s.append(P(
        "The nightly billing batch for 18 May 2026 started on schedule at 22:00 CEST "
        "and was expected to finish by 04:00. It finished at 08:40, four hours and "
        "forty minutes late. Because invoice dispatch is gated on batch completion, "
        "61,400 invoices that should have been sent before the 06:00 dispatch cut-off "
        "went out in the 09:00 run instead. Direct debit files for two partner banks "
        "missed their 07:00 submission slot and were submitted the following day.",
        SERIF))
    s.append(P(
        "No invoices were lost, duplicated or mis-stated. The delay was visible to "
        "customers only as an invoice arriving later in the day than usual. Group "
        "Finance confirmed on 19 May that the month-end close was not affected.",
        SERIF))

    s.append(P("2. Impact", SERIF_H))
    s.extend(bullets([
        "61,400 invoices dispatched 4h 40m late (of 208,000 in the run).",
        "2 direct debit submissions missed their bank cut-off; CHF 3.1m collected "
        "one day later than planned.",
        "34 support contacts, all resolved with a standard explanation.",
        "No financial loss. Interest cost of the one-day collection delay estimated "
        "at CHF 210.",
    ], SERIF))
    s.append(Spacer(1, 3))
    s.append(bar_chart(
        [[5.4, 5.6, 5.5, 5.8, 6.1, 6.4, 7.2, 8.1, 10.7]],
        ["10 May", "11 May", "12 May", "13 May", "14 May", "15 May", "16 May",
         "17 May", "18 May"],
        width=W, height=42 * mm, colours=(STEEL,), y_max=12, y_step=2,
        title="Nightly billing batch runtime, hours (window is 6.0 hours)"))
    s.append(P("Figure 1 &mdash; runtime had been growing for a week before the "
               "overrun. The 6-hour window is exceeded from 16 May onward.",
               CAPTION))

    s.append(P("3. Timeline (CEST)", SERIF_H))
    s.append(grid_table(
        ["When", "What happened"],
        [["2026-05-11", "Monthly pricing catalogue loaded. Row count grows from "
          "1.2m to 4.9m following the addition of the partner tariff tables."],
         ["2026-05-16 04:38", "Batch first exceeds its window, by 38 minutes. The "
          "overrun is logged but the alert threshold is set at 120 minutes, so "
          "nobody is notified."],
         ["2026-05-17 05:06", "Second overrun, 66 minutes. Again below the alert "
          "threshold."],
         ["2026-05-18 22:00", "Batch starts on schedule."],
         ["2026-05-19 01:12", "Step 4 (tariff resolution) enters its long phase; "
          "throughput drops to 190 accounts/second from a normal 1,400."],
         ["2026-05-19 04:00", "Window closes with the batch at 61% complete. "
          "Overrun alert fires at the 120-minute mark, 06:00."],
         ["2026-05-19 06:04", "On-call operator acknowledges; confirms the batch is "
          "progressing and elects to let it finish rather than restart."],
         ["2026-05-19 06:20", "Dispatch team informed that the 06:00 cut-off has "
          "been missed. Partner banks notified of the direct debit delay."],
         ["2026-05-19 08:40", "Batch completes successfully. Invoice dispatch runs "
          "at 09:00."],
         ["2026-05-21 10:00", "Post-incident review held."]],
        [26 * mm, W - 26 * mm], head_bg=colors.HexColor("#3A3A3A"),
        cell_style=ParagraphStyle("t6d", parent=SERIF, fontSize=8, leading=10.5,
                                  spaceAfter=0)))

    s.append(P("4. Root cause", SERIF_H))
    s.append(P(
        "Step 4 of the batch resolves a tariff for every account by scanning the "
        "pricing catalogue. The query relies on an index on "
        "<font face='Courier'>(tariff_code, valid_from)</font>. The partner tariff "
        "tables loaded on 11 May quadrupled the catalogue and introduced a large "
        "number of rows sharing a single tariff_code, which made that index "
        "unselective. The planner switched to a sequential scan per account, turning "
        "a linear step into an effectively quadratic one. Runtime therefore grew "
        "each night as more partner accounts were activated, crossing the window on "
        "16 May and overrunning badly on 18 May.", SERIF))
    s.append(P(
        "The growth was visible in the runtime metric for a week. It was not acted "
        "on because the only alert on this job fires at 120 minutes past the window, "
        "and the two earlier overruns were 38 and 66 minutes.", SERIF))

    s.append(P("5. Action plan", SERIF_H))
    s.append(grid_table(
        ["Ref", "Action", "Owner", "Due"],
        [["OPS-3401", "Batch Operations will keep an eye on the nightly runtime and "
          "escalate if it happens again.", "Batch Operations", "Ongoing"]],
        [20 * mm, W - 68 * mm, 30 * mm, 18 * mm],
        head_bg=colors.HexColor("#3A3A3A"),
        cell_style=ParagraphStyle("t6e", parent=SERIF, fontSize=8.5, leading=11,
                                  spaceAfter=0)))
    s.append(Spacer(1, 5))
    s.append(P(
        "The forum discussed indexing changes and an earlier alert threshold, but no "
        "owner was available before the quarter-end freeze and no further items were "
        "raised at this time.", SERIF))
    s.append(Spacer(1, 8))
    s.append(P("C. Eberhart<br/>Batch Operations<br/>2026-05-21", SERIF))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ============================================ 07 - complete except: no timeline =

def doc_07():
    path = OUT / "INC-5388-auth-service-latency-spike.pdf"
    W = A4[0] - 36 * mm
    BOX = ParagraphStyle("box", parent=BODY_S, fontSize=8, leading=10.5)

    def check(text, ticked=True):
        mark = "[X]" if ticked else "[&nbsp;&nbsp;]"
        return P(f"<font face='Courier-Bold' size=8.5>{mark}</font>&nbsp; {text}",
                 BOX)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(1.2)
        canvas.rect(10 * mm, 10 * mm, A4[0] - 20 * mm, A4[1] - 20 * mm,
                    stroke=1, fill=0)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 13 * mm,
                          "Form ITSM-14 (rev. 2025-11)  ·  Post-incident record  ·  "
                          "retain 7 years")
        canvas.drawRightString(A4[0] - 18 * mm, 13 * mm,
                               "Sheet %d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=18 * mm,
                            bottomMargin=18 * mm, leftMargin=18 * mm,
                            rightMargin=18 * mm,
                            title="ITSM-14 post-incident record INC-5388",
                            author="j.keller")
    s = []
    s.append(P("POST-INCIDENT RECORD &mdash; FORM ITSM-14", ParagraphStyle(
        "f7", parent=BODY, fontName="Helvetica-Bold", fontSize=12, leading=15,
        textColor=INK, alignment=1)))
    s.append(P("Complete one form per incident of severity SEV-3 or higher. "
               "All fields are mandatory.", ParagraphStyle(
                   "f7s", parent=SMALL, alignment=1)))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("1. Incident ref.", "INC-5388"),
        ("2. Short title", "Authentication latency spike after configuration "
                           "change; 22% of logins timed out"),
        ("3. Severity", "SEV-2"),
        ("4. Service", "auth-service v5.9.4 (session issuance), edge-gw"),
        ("5. Environment", "Production &mdash; all regions"),
        ("6. Date of incident", "2026-04-14"),
        ("7. Duration", "1 hour 38 minutes (09:41 &ndash; 11:19 UTC)"),
        ("8. Reported by", "Monitoring &mdash; alert AUTH-P99-LATENCY"),
        ("9. Incident manager", "J. Keller"),
        ("10. Form completed", "2026-04-17 by J. Keller"),
    ], W, label_w=32 * mm))

    s.append(P("11. Description of the incident", H2_PLAIN))
    s.append(P(
        "A configuration change deployed to auth-service at 09:38 UTC on 14 April "
        "2026 raised p99 login latency from 140 ms to just over 12 seconds. The edge "
        "gateway times out at 10 seconds, so 22% of login attempts returned a 504 to "
        "the customer. Sessions that were already established were unaffected, and "
        "no credentials were exposed or mishandled at any point.", BODY_S))
    s.append(P(
        "The change set <font face='Courier'>session.signing.mode=strict</font>, "
        "which forces a fresh read of the signing key from the hardware security "
        "module for every token issued instead of using the in-process cached key. "
        "The HSM handles roughly 400 operations per second; login peak is 2,900 per "
        "second. Requests queued behind the HSM until they timed out.", BODY_S))
    s.append(Spacer(1, 3))
    s.append(dashboard_screenshot(width=W * 0.62, height=40 * mm,
                                  title="grafana / auth-service / production",
                                  panel_titles=("p99 login latency (ms)",
                                                "504 rate, %")))
    s.append(P("Screenshot taken at 10:52 UTC and attached to the incident record.",
               CAPTION))

    s.append(P("12. Impact assessment", H2_PLAIN))
    s.append(grid_table(
        ["Category", "Assessment"],
        [["Customers affected", "~148,000 failed login attempts; 61,000 unique "
                                "accounts"],
         ["Financial", "CHF 22,000 estimated deferred revenue; no direct loss"],
         ["Data", "None. No credential exposure; no records modified."],
         ["Regulatory", "Not reportable. Availability event, not a security event."],
         ["SLO", "Login availability budget for April: 64% consumed"]],
        [34 * mm, W - 34 * mm], head_bg=colors.HexColor("#404040")))

    s.append(P("13. Root cause", H2_PLAIN))
    s.append(panel([P(
        "<b>The strict signing mode was enabled in production without capacity "
        "analysis against the HSM.</b> In strict mode every token issuance performs "
        "an HSM signing operation. The HSM's rated throughput of about 400 "
        "operations per second is roughly one seventh of peak login volume, so the "
        "request queue in front of it grew without bound and latency rose until "
        "requests hit the gateway's 10-second timeout. The setting had been "
        "validated in staging, where login volume is about 30 requests per second "
        "and the HSM is comfortably within capacity.", BODY_S)], W))

    s.append(P("14. Detection and response checklist", H2_PLAIN))
    checks = [
        check("Incident detected by automated monitoring (not by a customer)"),
        check("Alert paged the correct on-call rota within 5 minutes"),
        check("Severity assigned within 15 minutes of detection"),
        check("Status page updated within 30 minutes"),
        check("Change causing the incident identified from the change log", True),
        check("Rollback tested before being applied to production", False),
        check("Customer communication issued", True),
        check("Timeline of events recorded in this form", False),
        check("Root cause established and stated above", True),
        check("Actions raised in Jira with named owners and due dates", True),
    ]
    ct = Table([[checks[i], checks[i + 5]] for i in range(5)],
               colWidths=[W / 2, W / 2])
    ct.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    s.append(ct)
    s.append(Spacer(1, 3))
    s.append(P("Where a box is unticked, explain below. &mdash; <i>Rollback was "
               "applied directly to production without a staging rehearsal, on the "
               "incident manager's authority, because the change was a single "
               "configuration key. Section 15 of this form was not completed; see "
               "note at item 17.</i>", BODY_S))

    s.append(P("15. Sequence of events", H2_PLAIN))
    s.append(P("<i>[This section of the form has not been completed.]</i>",
               ParagraphStyle("empty", parent=BODY_S, textColor=GREY)))

    s.append(P("16. Action plan", H2_PLAIN))
    s.append(grid_table(
        ["Jira", "Action", "Owner", "Due", "Status"],
        [["IAM-611", "Revert session.signing.mode to cached and document that strict "
          "mode may not be enabled without an HSM capacity review.", "J. Keller",
          "2026-04-15", "Done"],
         ["IAM-612", "Add HSM operations-per-second to the pre-change checklist for "
          "any auth-service configuration change.", "J. Keller", "2026-04-30",
          "Done"],
         ["IAM-613", "Load-test staging at production-equivalent login volume "
          "before any signing-path change; provision a second HSM for the test "
          "environment.", "A. Novak", "2026-05-29", "Done"],
         ["IAM-614", "Add an HSM queue-depth alert that pages at 80% of rated "
          "throughput.", "M. Dubois", "2026-05-08", "Done"]],
        [17 * mm, W - 77 * mm, 21 * mm, 20 * mm, 15 * mm],
        head_bg=colors.HexColor("#404040")))

    s.append(P("17. Notes", H2_PLAIN))
    s.append(P(
        "Item 15 was left blank. The bridge recording that the sequence would have "
        "been reconstructed from was not retained past its 72-hour expiry, and the "
        "form was completed on 17 April. The incident manager judged that an "
        "approximate sequence would be worse than none. This is itself raised as "
        "ITSM-90 (retain incident bridge recordings for 30 days), which is outside "
        "the scope of this record.", BODY_S))
    s.append(Spacer(1, 6))
    s.append(P("Signed: J. Keller, Incident Manager &nbsp;·&nbsp; "
               "Countersigned: R. Bianchi, Head of Platform &nbsp;·&nbsp; "
               "2026-04-17", SMALL))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ========================================= 08 - complete except: vague description =

def doc_08():
    path = OUT / "INC-5401-api-issue-thread-export.pdf"
    W = A4[0] - 40 * mm
    HDR = ParagraphStyle("mh", parent=MONO_S, fontSize=7.5, leading=10)
    QUOTE = ParagraphStyle("q", parent=BODY_S, leftIndent=8, textColor=colors.HexColor(
        "#555555"), fontSize=7.5, leading=10)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#EEEEEE"))
        canvas.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#444444"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(20 * mm, A4[1] - 9 * mm,
                          "Mail archive export  ·  thread: [INC-5401] postmortem")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 9 * mm,
                               "4 messages  ·  exported 2026-08-20 by "
                               "compliance@northwind")
        canvas.setStrokeColor(RULE)
        canvas.line(20 * mm, 13 * mm, A4[0] - 20 * mm, 13 * mm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(GREY)
        canvas.drawString(20 * mm, 9 * mm, "Retained under records policy RP-4. "
                                           "This export is the incident's "
                                           "post-incident record of file.")
        canvas.drawRightString(A4[0] - 20 * mm, 9 * mm, "%d" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm,
                            bottomMargin=16 * mm, leftMargin=20 * mm,
                            rightMargin=20 * mm,
                            title="INC-5401 postmortem thread export",
                            author="mail archive")

    def message(frm, to, date, subject, body_flowables):
        head = P(f"<b>From:</b> {frm}<br/><b>To:</b> {to}<br/>"
                 f"<b>Date:</b> {date}<br/><b>Subject:</b> {subject}", HDR)
        inner = Table([[head]] + [[f] for f in body_flowables],
                      colWidths=[W - 10])
        inner.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F7F7F7")),
            ("BOX", (0, 0), (-1, -1), 0.4, RULE),
            ("LINEBELOW", (0, 0), (0, 0), 0.4, RULE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return inner

    s = []
    s.append(message(
        "d.moreau@northwind.example", "platform-all@northwind.example",
        "Mon, 10 Aug 2026 08:12:04 +0200",
        "[INC-5401] postmortem - API issue on 07 Aug",
        [P("All,", BODY_S),
         P("Writing up INC-5401 as agreed. Jira reference is INC-5401 and the "
           "follow-up items are under API-2201, API-2202 and API-2203.", BODY_S),
         P("<b>What happened</b>", ParagraphStyle("b8", parent=BODY_S,
                                                  fontName="Helvetica-Bold")),
         P("There was an issue in prod on Friday affecting the API layer. Some "
           "requests did not behave as expected for a period during the morning and "
           "a subset of consumers were impacted. The situation was investigated by "
           "the team, appropriate remediation was applied, and normal operation was "
           "restored the same day. Impact was limited and largely mitigated by "
           "existing controls.", BODY_S),
         P("<b>Timeline (CEST, 7 Aug 2026)</b>", ParagraphStyle(
             "b8b", parent=BODY_S, fontName="Helvetica-Bold")),
         P("09:14 &mdash; alert API-5XX-RATE fires (threshold 2% over 5 min).<br/>"
           "09:17 &mdash; d.moreau acknowledges.<br/>"
           "09:26 &mdash; SEV-3 declared; bridge opened with s.hartmann.<br/>"
           "09:48 &mdash; correlation found with the 08:55 deployment of "
           "api-gateway 7.3.0.<br/>"
           "10:02 &mdash; decision to roll back to 7.2.4.<br/>"
           "10:11 &mdash; rollback started.<br/>"
           "10:29 &mdash; rollback complete across all four availability zones.<br/>"
           "10:35 &mdash; error rate at baseline.<br/>"
           "11:05 &mdash; 30 minutes clean; incident closed.", MONO_S),
         P("<b>Root cause</b>", ParagraphStyle("b8c", parent=BODY_S,
                                               fontName="Helvetica-Bold")),
         P("api-gateway 7.3.0 introduced a stricter JSON body parser. Requests "
           "sending a numeric field as a quoted string &mdash; which the previous "
           "parser accepted and coerced &mdash; were rejected with a 500 rather than "
           "a 400, and the gateway did not fall back. Two partner integrations send "
           "the <font face='Courier'>quantity</font> field this way. The change was "
           "not called out as breaking in the release notes.", BODY_S),
         P("<b>Actions</b>", ParagraphStyle("b8d", parent=BODY_S,
                                            fontName="Helvetica-Bold")),
         P("API-2201 &mdash; restore lenient coercion behind a per-consumer flag and "
           "deprecate it with 90 days' notice. Owner d.moreau, due 2026-09-04.<br/>"
           "API-2202 &mdash; contract tests in CI running the top 20 partner request "
           "shapes against every gateway release candidate. Owner t.iversen, due "
           "2026-09-18.<br/>"
           "API-2203 &mdash; release notes must classify every parser or validation "
           "change as breaking or non-breaking before sign-off. Owner s.hartmann, "
           "due 2026-08-28.", MONO_S),
         P("Regards,<br/>Denis", BODY_S)]))
    s.append(Spacer(1, 5))

    s.append(message(
        "r.bianchi@northwind.example", "d.moreau@northwind.example",
        "Mon, 10 Aug 2026 09:41:55 +0200",
        "Re: [INC-5401] postmortem - API issue on 07 Aug",
        [P("Denis,", BODY_S),
         P("The timeline, cause and actions are fine. The 'what happened' section "
           "does not tell me what actually broke. Which endpoints? How many "
           "requests failed, out of how many? Which two partners, and what did they "
           "see &mdash; failed orders, or retried ones? Was anything lost?", BODY_S),
         P("As written I cannot tell whether this was a nuisance or a serious "
           "event, and neither will anyone reading it in six months.", BODY_S),
         P("R.", BODY_S),
         P("&gt; There was an issue in prod on Friday affecting the API layer. Some<br/>"
           "&gt; requests did not behave as expected for a period during the "
           "morning and<br/>"
           "&gt; a subset of consumers were impacted. The situation was "
           "investigated by<br/>"
           "&gt; the team, appropriate remediation was applied [...]", QUOTE)]))
    s.append(Spacer(1, 5))

    s.append(message(
        "d.moreau@northwind.example", "r.bianchi@northwind.example",
        "Mon, 10 Aug 2026 11:20:31 +0200",
        "Re: [INC-5401] postmortem - API issue on 07 Aug",
        [P("Understood. I will get the numbers from the gateway logs and send a "
           "revised description this week.", BODY_S)]))
    s.append(Spacer(1, 5))

    s.append(message(
        "compliance@northwind.example", "records@northwind.example",
        "Thu, 20 Aug 2026 16:02:10 +0200",
        "FW: [INC-5401] postmortem - API issue on 07 Aug",
        [P("Filing this thread as the post-incident record for INC-5401. No revised "
           "description was received; the Jira issue was closed on 18 August with "
           "all three actions marked done.", BODY_S),
         P("Attachment: inc-5401-error-rate.png (rendered below)", SMALL),
         P("", BODY_S),
         line_chart(
             [[0.3, 0.4, 2.6, 4.1, 4.4, 4.2, 3.9, 1.1, 0.4, 0.3]],
             ["08:30", "09:00", "09:15", "09:30", "09:45", "10:00", "10:15",
              "10:29", "10:45", "11:05"],
             width=W - 20, height=40 * mm, colours=(RED,), y_min=0, y_max=6,
             y_step=1, title="api-gateway 5xx rate, % of requests (7 Aug, CEST)",
             band=(1.6, 7.2)),
         P("Rendered from the attachment. Shaded region is the deployment window "
           "for api-gateway 7.3.0.", CAPTION)]))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ================================== 09 - complete except: root cause undetermined =

def doc_09():
    path = OUT / "INC-5455-intermittent-upload-stalls.pdf"
    W = A4[0] - 40 * mm

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#3A3F4B"))
        canvas.rect(0, 0, 8 * mm, A4[1], stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.saveState()
        canvas.translate(5.5 * mm, 30 * mm)
        canvas.rotate(90)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(0, 0, "INC-5455  ·  POST-INCIDENT REVIEW  ·  "
                                "ROOT CAUSE NOT ESTABLISHED")
        canvas.restoreState()
        canvas.setStrokeColor(RULE)
        canvas.line(20 * mm, 14 * mm, A4[0] - 15 * mm, 14 * mm)
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(20 * mm, 10 * mm,
                          "Cloud Storage Platform  ·  draft 3  ·  2026-03-30")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, "Page %d of 2" % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=18 * mm,
                            bottomMargin=18 * mm, leftMargin=20 * mm,
                            rightMargin=15 * mm,
                            title="INC-5455 intermittent upload stalls",
                            author="m.dubois")
    s = []
    s.append(P("Intermittent 30-second stalls on customer file uploads", H1))
    s.append(P("INC-5455 &middot; post-incident review, draft 3 &middot; "
               "M. Dubois, Cloud Storage Platform &middot; 2026-03-30", SMALL))
    s.append(Spacer(1, 5))
    s.append(kv_table([
        ("Jira issue", "INC-5455 &nbsp;·&nbsp; investigation STO-1180, "
                       "actions STO-1181 to STO-1185"),
        ("Severity", "SEV-3 &mdash; degraded, intermittent, self-recovering"),
        ("Environment", "Production &mdash; upload-svc v3.11.0, object store "
                        "cluster obj-eu-2, F5 load balancers"),
        ("First observed", "2026-03-02 (retrospectively; first customer report "
                           "2026-03-09)"),
        ("Last observed", "2026-03-27 08:41 CET"),
        ("Frequency", "14 episodes over 25 days, each 28&ndash;34 seconds, no "
                      "pattern by hour or weekday"),
        ("Status", "<b>Open</b> &mdash; monitoring in place, cause not established"),
    ], W))

    s.append(P("1. Description", H2))
    s.append(P(
        "Between 2 and 27 March 2026, customer file uploads through upload-svc "
        "stalled intermittently. During an episode, an upload that had been "
        "streaming normally stopped transferring for 28 to 34 seconds and then "
        "resumed at full speed and completed successfully. The client showed a "
        "frozen progress bar. Uploads started during an episode were also affected; "
        "downloads, listing and deletion were not.", BODY))
    s.append(P(
        "Fourteen episodes were confirmed from server-side traces. Each affected "
        "every upload in flight on one of the six upload-svc nodes, but only ever "
        "one node at a time, and never the same node twice in succession. 9,240 "
        "uploads were delayed in total. Eleven uploads &mdash; all from clients with "
        "a 30-second timeout &mdash; failed outright and had to be retried by the "
        "customer. No file was corrupted or partially stored: the object store "
        "either had the complete object or nothing.", BODY))

    s.append(P("2. Impact", H2))
    s.extend(bullets([
        "9,240 uploads delayed by roughly 30 seconds across 14 episodes.",
        "11 uploads failed and were retried manually by customers.",
        "6 support tickets, 2 escalated by named enterprise accounts.",
        "No data loss and no corruption. Upload SLO (99.5% under 60s for a 10 MB "
        "file) breached in March: 99.31%.",
    ]))
    s.append(Spacer(1, 3))
    s.append(bar_chart(
        [[31, 29, 33, 28, 30, 34, 29, 31, 30, 28, 32, 33, 29, 30]],
        ["02", "05", "09", "11", "13", "16", "17", "19", "20", "22", "24", "25",
         "26", "27"],
        width=W, height=40 * mm, colours=(AMBER,), y_max=40, y_step=10,
        title="Episode duration in seconds, by day in March 2026"))
    s.append(P("Figure 1 &mdash; duration is remarkably consistent at about 30 "
               "seconds, which is itself the strongest clue and is discussed under "
               "hypothesis B.", CAPTION))

    s.append(P("3. Timeline (CET)", H2))
    s.append(grid_table(
        ["When", "What happened"],
        [["2026-03-02 14:22", "First episode, visible only in traces. No alert; the "
          "upload latency alert averages over 5 minutes and a 30-second stall on "
          "one node does not move the average enough to fire."],
         ["2026-03-09 10:05", "First customer report. Treated as an isolated client "
          "network problem and closed."],
         ["2026-03-13 09:30", "Third report. M. Dubois correlates the reports with "
          "trace data and finds nine prior episodes. INC-5455 raised."],
         ["2026-03-16 11:00", "Investigation begins. Continuous packet capture "
          "enabled on all six upload nodes."],
         ["2026-03-17 15:48", "Episode captured in full for the first time. The "
          "capture shows the node stops reading from its sockets; TCP windows go to "
          "zero; no error is logged."],
         ["2026-03-19", "GC logs, thread dumps and kernel scheduler traces reviewed "
          "for the 17 March episode. No stop-the-world pause longer than 180 ms. "
          "Hypothesis A weakened."],
         ["2026-03-20 02:00", "Object store vendor engaged with the captures. "
          "Vendor confirms no server-side throttling and no errors on their side "
          "during the episode windows."],
         ["2026-03-23", "F5 load balancer firmware and connection-reuse settings "
          "reviewed. A 30-second idle timeout is found on the internal pool and is "
          "the basis of hypothesis B."],
         ["2026-03-25 16:00", "Review with SRE, networking and the vendor. No "
          "hypothesis can be confirmed with the evidence held."],
         ["2026-03-26 09:00", "Connection pool recycling changed as a mitigation "
          "(STO-1181), deployed to two of six nodes as a controlled experiment."],
         ["2026-03-27 08:41", "Fourteenth and last episode &mdash; on one of the "
          "four unchanged nodes."],
         ["2026-03-30", "Review held. Document issued with the cause "
          "unestablished."]],
        [24 * mm, W - 24 * mm],
        cell_style=ParagraphStyle("t9t", parent=BODY_S, fontSize=7.2, leading=9.2)))

    s.append(P("4. Root cause", H2))
    s.append(panel([
        P("<b>The root cause of this incident has not been established.</b> Three "
          "hypotheses were investigated. None could be confirmed or ruled out with "
          "the evidence available, and no episode has occurred since 27 March, so "
          "there is nothing left to observe. This document is issued with the cause "
          "open rather than held indefinitely.", BODY)],
        W, bg=colors.HexColor("#FFF4E5"), bar=AMBER))
    s.append(Spacer(1, 4))
    s.append(grid_table(
        ["", "Hypothesis", "Evidence for", "Evidence against", "Verdict"],
        [["A", "Garbage collection pause in upload-svc",
          "Stalls affect one JVM at a time and end without intervention, which fits "
          "a stop-the-world pause.",
          "GC logs for the captured episode show no pause above 180 ms. A 30-second "
          "pause would be logged.", "Unlikely, not excluded"],
         ["B", "F5 idle timeout on the internal connection pool",
          "The pool idle timeout is exactly 30 seconds, matching the observed "
          "duration closely.",
          "The stall affects connections that are actively transferring, which "
          "should never be idle. The vendor cannot explain this.",
          "Plausible, unproven"],
         ["C", "Silent throttling or a failover in the object store",
          "Only one node is affected at a time, consistent with per-client "
          "throttling.",
          "The vendor's own telemetry shows no throttling and no errors during any "
          "episode window. We cannot audit this independently.",
          "Unproven, cannot verify"]],
        [7 * mm, 32 * mm, (W - 39 * mm) / 3 + 4 * mm, (W - 39 * mm) / 3 + 4 * mm,
         (W - 39 * mm) / 3 - 8 * mm],
        head_bg=colors.HexColor("#3A3F4B"),
        cell_style=ParagraphStyle("t9", parent=BODY_S, fontSize=7, leading=9)))
    s.append(Spacer(1, 4))
    s.append(P(
        "What is known with confidence: during an episode the affected node stops "
        "reading from its client sockets, no error is logged by any component, and "
        "the condition clears itself after approximately 30 seconds. What is not "
        "known: why it stops reading. The remaining actions are therefore weighted "
        "towards evidence collection rather than repair.", BODY))

    s.append(P("5. Action plan", H2))
    s.append(grid_table(
        ["Jira", "Action", "Type", "Owner", "Due", "Status"],
        [["STO-1181", "Recycle pooled connections every 20 seconds so that no "
          "connection can reach the 30-second idle timeout. Mitigates hypothesis B "
          "without confirming it.", "Mitigate", "M. Dubois", "2026-03-26",
          "Done (2 of 6 nodes)"],
         ["STO-1182", "Roll the connection recycling change to the remaining four "
          "nodes and hold the configuration for 60 days.", "Mitigate", "M. Dubois",
          "2026-04-03", "Open"],
         ["STO-1183", "Alert on any single upload node whose socket read throughput "
          "falls to zero for more than 5 seconds, so that the next episode pages "
          "immediately rather than being found in traces.", "Detect", "A. Novak",
          "2026-04-10", "Open"],
         ["STO-1184", "Keep continuous packet capture and JFR recording enabled on "
          "all upload nodes until 2026-06-30, with a 7-day retention.",
          "Investigate", "M. Dubois", "2026-04-03", "Open"],
         ["STO-1185", "Request per-connection server-side telemetry from the object "
          "store vendor under the support contract, so hypothesis C can be tested "
          "rather than taken on trust.", "Investigate", "R. Bianchi", "2026-04-24",
          "Open"]],
        [18 * mm, W - 88 * mm, 17 * mm, 20 * mm, 18 * mm, 15 * mm],
        head_bg=colors.HexColor("#3A3F4B")))
    s.append(Spacer(1, 5))
    s.append(P(
        "<b>Review decision (2026-03-30).</b> INC-5455 stays open at SEV-3 with no "
        "further investigation resourced. If a fifteenth episode occurs, STO-1183 "
        "will page and the incident returns to active investigation with the "
        "instrumentation from STO-1184 already in place. If none occurs by 30 June "
        "2026 the incident will be closed with the cause recorded as undetermined.",
        BODY))

    doc.build(s, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ================================================ 10 - several defects at once =

def doc_10():
    """Scanned-looking typewriter memo. Drawn on the canvas so the page can be
    skewed the way a scan is."""
    path = OUT / "prod-incident-note-2026-02-11-scan.pdf"
    c = pdfcanvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Scanned incident note 2026-02-11")
    c.setAuthor("scanner")

    # paper tint and a few deterministic scan speckles
    def paper(page):
        c.setFillColor(colors.HexColor("#F3F1EC"))
        c.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#DCD8CF"))
        seed = 12345 + page * 7919
        for i in range(140):
            seed = (1103515245 * seed + 12345) % 2147483648
            x = (seed >> 7) % int(A4[0])
            seed = (1103515245 * seed + 12345) % 2147483648
            y = (seed >> 7) % int(A4[1])
            seed = (1103515245 * seed + 12345) % 2147483648
            r = 0.2 + ((seed >> 9) % 5) / 10.0
            c.circle(x, y, r, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#C9C4BA"))
        c.setLineWidth(0.7)
        c.rect(9 * mm, 9 * mm, A4[0] - 18 * mm, A4[1] - 18 * mm, stroke=1, fill=0)

    LEFT = 24 * mm
    RIGHT = A4[0] - 24 * mm
    WIDTH = RIGHT - LEFT

    state = {"y": 0.0, "page": 0}

    def new_page(first=False):
        if not first:
            c.restoreState()
            c.showPage()
        state["page"] += 1
        paper(state["page"])
        c.saveState()
        c.translate(3 * mm, -2 * mm)
        c.rotate(-0.6)
        c.setFillColor(colors.HexColor("#1A1A1A"))
        state["y"] = A4[1] - 26 * mm

    def line(text, font="Courier", size=8.6, gap=11.0, colour="#1A1A1A",
             indent=0.0):
        if state["y"] < 22 * mm:
            new_page()
        c.setFont(font, size)
        c.setFillColor(colors.HexColor(colour))
        c.drawString(LEFT + indent, state["y"], text)
        state["y"] -= gap

    def wrap(text, font="Courier", size=8.6, gap=11.0, indent=0.0, hang=0.0):
        words = text.split()
        cur = ""
        avail = WIDTH - indent
        out = []
        for w in words:
            trial = (cur + " " + w).strip()
            if stringWidth(trial, font, size) <= avail:
                cur = trial
            else:
                out.append(cur)
                cur = w
                avail = WIDTH - indent - hang
        if cur:
            out.append(cur)
        for i, ln in enumerate(out):
            line(ln, font, size, gap, indent=indent + (hang if i else 0))

    def blank(n=1):
        state["y"] -= 11.0 * n

    new_page(first=True)

    # a rubber stamp, drawn skewed like the rest of the page
    c.saveState()
    c.translate(RIGHT - 44 * mm, A4[1] - 34 * mm)
    c.rotate(9)
    c.setStrokeColor(colors.HexColor("#8B2B2B"))
    c.setFillColor(colors.HexColor("#8B2B2B"))
    c.setLineWidth(1.4)
    c.rect(0, 0, 40 * mm, 13 * mm, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(20 * mm, 7.5 * mm, "SCANNED COPY")
    c.setFont("Helvetica", 6)
    c.drawCentredString(20 * mm, 3 * mm, "records office  ·  11 FEB 2026")
    c.restoreState()

    line("PRODUCTION INCIDENT NOTE", "Courier-Bold", 12, 15)
    line("Warehouse Systems / Distribution Centre 2", "Courier", 8.6, 13)
    line("-" * 68, "Courier", 8.6, 14)
    line("Jira ref .......: TBD", "Courier", 8.6)
    line("Raised by ......: night shift supervisor (name not recorded)")
    line("Date ...........: 11 February 2026")
    line("System .........: WMS pick-and-pack, conveyor controller PLC-7")
    line("Severity .......: major (per shift log)")
    line("Distribution ...: operations manager, IT service desk")
    blank()
    line("1. WHAT HAPPENED", "Courier-Bold", 9.5, 13)
    wrap("The pick-and-pack line in DC2 stopped accepting scans during the night "
         "shift. Operators could not confirm picks at the handheld terminals and "
         "the conveyor was halted manually to prevent totes backing up at the "
         "sorter. The line was down for most of the shift. Roughly 4,000 units did "
         "not ship on the first van and were carried to the following day. The "
         "morning shift found the system working again.")
    blank()
    line("2. TIMELINE", "Courier-Bold", 9.5, 13)
    wrap("Sometime during the night the terminals stopped working. It was fixed "
         "later on after IT were called and things were restarted.")
    blank()
    line("3. WHAT WE DID", "Courier-Bold", 9.5, 13)
    wrap("IT service desk was called. The WMS application servers were restarted "
         "and the PLC-7 controller was power cycled. After that the terminals "
         "worked again. Nobody has been able to say for certain which of the two "
         "restarts fixed it, and no logs were kept from before the restart because "
         "the terminal log buffer only holds one hour.")
    blank()
    line("4. IMPACT", "Courier-Bold", 9.5, 13)
    wrap("- around 4,000 units delayed by one day", "Courier", 8.6, 11, hang=10)
    wrap("- one van departed empty, cost not calculated", "Courier", 8.6, 11,
         hang=10)
    wrap("- two agency staff sent home early", "Courier", 8.6, 11, hang=10)
    wrap("- no stock discrepancy found at the morning count", "Courier", 8.6, 11,
         hang=10)
    blank()
    line("5. ACTIONS", "Courier-Bold", 9.5, 13)
    wrap("- look at the terminal wifi in DC2", "Courier", 8.6, 11, hang=10)
    wrap("- check whether the PLC firmware is up to date", "Courier", 8.6, 11,
         hang=10)
    wrap("- ask the vendor about the log buffer size", "Courier", 8.6, 11, hang=10)
    wrap("- consider a proper runbook for the night shift", "Courier", 8.6, 11,
         hang=10)
    blank()
    wrap("Note: this note was written up from the shift log on 11/02 by the "
         "operations coordinator. It has not been reviewed with IT. A formal "
         "postmortem has not been scheduled.")
    blank(2)
    line("signed: ....(illegible)....        date: 11/02/2026", "Courier", 8.6)
    blank()
    line("-" * 68, "Courier", 8.6, 12)
    line("attachment: shift log extract (photocopy, partly cut off)", "Courier-Oblique",
         7.5, 12)

    # a photocopied-looking extract block, deliberately clipped at the edge
    c.setStrokeColor(colors.HexColor("#9A958B"))
    c.setLineWidth(0.6)
    box_y = state["y"] - 40 * mm
    c.rect(LEFT, box_y, WIDTH, 38 * mm, stroke=1, fill=0)
    c.setFillColor(colors.HexColor("#E7E3DA"))
    c.rect(LEFT, box_y, WIDTH, 38 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#3A3A3A"))
    rows = [
        "DC2 NIGHT SHIFT LOG - 10/11 FEB",
        "22:00  shift start, 14 pickers, 2 agency",
        "23:1?  terminals slow, restarted handhelds - no",
        "00:0?  no scans going through at all, called IT",
        "0?:??  IT restarted servers",
        "03:20  still nothing, PLC power cycled",
        "0?:45  scans working, conveyor restarted",
        "05:30  van 1 departed empty, van 2 part loaded",
    ]
    ty = box_y + 33 * mm
    for r in rows:
        c.setFont("Courier", 7.4)
        c.drawString(LEFT + 4 * mm, ty, r)
        ty -= 9
    c.setFillColor(colors.HexColor("#E7E3DA"))
    c.rect(RIGHT - 16 * mm, box_y, 16 * mm, 38 * mm, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor("#9A958B"))
    c.line(RIGHT - 16 * mm, box_y, RIGHT - 16 * mm, box_y + 38 * mm)
    c.setFont("Helvetica-Oblique", 6)
    c.setFillColor(colors.HexColor("#7A756B"))
    c.drawCentredString(RIGHT - 8 * mm, box_y + 19 * mm, "cut off")

    c.restoreState()
    c.showPage()
    c.save()
    return path


ALL = [doc_06, doc_07, doc_08, doc_09, doc_10]
