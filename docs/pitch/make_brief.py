"""Build the BharatBench investor brief (4 pages, A4)."""

import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = sys.argv[1]
# Segoe UI has the rupee sign; the built-in Helvetica does not.
pdfmetrics.registerFont(TTFont("UI", "C:/Windows/Fonts/segoeui.ttf"))
pdfmetrics.registerFont(TTFont("UI-Bold", "C:/Windows/Fonts/segoeuib.ttf"))
pdfmetrics.registerFontFamily("UI", normal="UI", bold="UI-Bold", italic="UI", boldItalic="UI-Bold")
PRIMARY = colors.HexColor("#7C5CFF")
INK = colors.HexColor("#1E1B2E")
MUTED = colors.HexColor("#6B6880")
SOFT = colors.HexColor("#F3F0FA")
LINE = colors.HexColor("#E8E4F3")
GOOD = colors.HexColor("#16A34A")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontName="UI-Bold", fontSize=22, leading=26, textColor=INK, alignment=TA_LEFT, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontName="UI", fontSize=10.5, leading=14, textColor=MUTED, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="UI-Bold", fontSize=13, leading=16, textColor=PRIMARY, spaceBefore=9, spaceAfter=4)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName="UI-Bold", fontSize=10, leading=13, textColor=INK, spaceBefore=4, spaceAfter=1)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontName="UI", fontSize=9, leading=12.2, textColor=INK, spaceAfter=3)
SMALL = ParagraphStyle("SMALL", parent=BODY, fontSize=7.6, leading=9.6, textColor=MUTED)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.2, leading=10.4, spaceAfter=0)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="UI-Bold")
BIG = ParagraphStyle("BIG", parent=BODY, fontName="UI-Bold", fontSize=17, leading=19, textColor=PRIMARY, spaceAfter=0)
KPIL = ParagraphStyle("KPIL", parent=BODY, fontSize=7.6, leading=9.4, textColor=MUTED, spaceAfter=0)


def p(t, s=BODY):
    return Paragraph(t, s)


def table(rows, widths, header=True, zebra=True):
    data = [[p(c, CELLB if (header and i == 0) else CELL) if isinstance(c, str) else c for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, PRIMARY)]
    t.setStyle(TableStyle(st))
    return t


def kpis(items):
    cells = [[p(v, BIG) for v, _ in items], [p(k, KPIL) for _, k in items]]
    w = (A4[0] - 32 * mm) / len(items)
    t = Table(cells, colWidths=[w] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
        ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.white),
    ]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("UI", 7.2)
    canvas.setFillColor(MUTED)
    canvas.drawString(16 * mm, 9 * mm, "BharatBench · The Real Phone Test · Team BrahMoss · HackFront 2026 · bharatbench-orpin.vercel.app")
    canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"{doc.page} / 4")
    canvas.restoreState()


W = A4[0] - 32 * mm
s = []

# ---------------- Page 1: the business in one page ----------------
s += [
    p("BharatBench", H1),
    p("The Real Phone Test — catch the crashes and freezes that cost Android apps their users and their Play Store "
      "ranking, on the phones Indian users actually carry. Investor brief, 22 Nov 2026.", SUB),
    kpis([("18", "test runs executed on a real Android device"), ("207", "issues found across 9 apps"),
          ("27", "critical issues (ANRs, failed launches)"), ("3.9 min", "median device test run")]),
    Spacer(1, 3),
    p("Platform data from the live system (45 runs, 22 Nov 2026). Early, team-run usage — not customer traction.", SMALL),
    p("The problem", H2),
    p("Indian developers build and test on fast phones and office Wi-Fi; their users are on entry-level phones, patchy "
      "networks and nearly full storage. The gap shows up as freezes (ANRs) and crashes after launch. Google Play treats "
      "an app as having bad behaviour above <b>0.47% user-perceived ANR rate</b> or <b>1.09% crash rate</b> and can reduce its "
      "visibility (Android vitals). In an India survey, <b>slow loading (34%)</b> and <b>freezing/crashing (29%)</b> were the top "
      "reasons people stopped using an app (Statista, 2023)."),
    p("What we built (working today)", H2),
    table([
        ["Capability", "What the customer sees", "Status"],
        ["Real-phone test lab", "APK (or GitHub release link) installed on real Android 12 with a hard 2 GB memory cap, "
         "2 Mbps / high-latency network, network drops, app kill-and-restore", "Live"],
        ["Watch it test", "Phone slides in and streams the screen while the agent taps and types; step-by-step replay after", "Live"],
        ["Security checks", "APK scan + 7 on-device checks (secrets in storage, log leaks, exported screens, plain-HTTP traffic)", "Live"],
        ["Business-impact report", "Issues ranked by users affected; Play Store risk; before/after score; AI fix per issue, "
         "grounded only in captured evidence", "Live"],
        ["Agent that writes tests", "Describe a scenario in chat (\"sign up with a wrong email\") — agent writes and runs it; "
         "optional test account for logged-in + offline testing", "Live, early"],
        ["Voice briefing", "\"Brief my team\": 60-second summary for PMs/founders in 11 Indian languages", "Live (secondary)"],
    ], [34 * mm, W - 34 * mm - 24 * mm, 24 * mm]),
    p("Why now / why us", H2),
    p("• India's sub-₹15k phones are getting <b>more</b> memory-constrained, not less: memory's share of the bill of materials "
      "rose from under 20% to over 45% (2026 reporting), so OEMs keep base RAM low. • AI agents can now drive apps and explain "
      "evidence at low cost (₹10 / ₹25 per million tokens on Sarvam). • No major testing cloud we found offers a 2 GB-class device "
      "profile, India network profiles or INR pricing. • We shipped a working real-device lab, agent and CI/CD in a hackathon."),
    PageBreak(),
]

# ---------------- Page 2: market, customer, competition ----------------
s += [
    p("Who pays, and against whom", H2),
    table([
        ["Segment", "Pain", "Buyer", "Why they switch to us"],
        ["App startups (fintech, edtech, quick-commerce)", "Bad reviews + churn from freezes on budget phones; no device lab",
         "CTO / Eng lead", "INR, self-serve, results in minutes, no device purchase"],
        ["App agencies", "Ship many client apps; need proof of quality for each", "Agency owner",
         "Per-app pricing, shareable client reports, before/after scores"],
        ["Enterprise & public-sector apps", "Must work for every citizen on any phone; security review", "QA / security lead",
         "On-device security checks + reliability in one report; India hosting"],
    ], [38 * mm, 50 * mm, 25 * mm, W - 113 * mm]),
    p("Competition (public pricing, Nov 2026)", H2),
    table([
        ["Tool", "Price (USD)", "2 GB-class profile", "India network", "On-device security", "AI agent tests", "INR"],
        ["BrowserStack App Automate", "$99–225 / mo", "No", "Generic throttling", "Separate products", "Limited", "No"],
        ["LambdaTest / TestMu", "$39–199 / mo", "No", "—", "—", "Some", "No"],
        ["Sauce Labs", "$39–49 / mo + concurrency", "No", "2G/3G presets", "No", "—", "No"],
        ["Firebase Test Lab", "$1–5 / device-hr", "No", "No", "No", "Robo crawl", "No"],
        ["AWS Device Farm", "$0.17 / device-min", "No", "—", "No", "No", "No"],
        ["Momentic (AI QA)", "$500 / mo + usage", "No", "No", "No", "Yes", "No"],
        ["NowSecure / Appknox", "Quote; ~$18k / app / yr reported", "No", "No", "Yes", "No", "No"],
        ["<b>BharatBench</b>", "<b>₹0–9,999 / mo</b>", "<b>Yes</b>", "<b>Yes</b>", "<b>Yes</b>", "<b>Yes</b>", "<b>Yes</b>"],
    ], [34 * mm, 30 * mm, 21 * mm, 23 * mm, 25 * mm, 20 * mm, W - 153 * mm]),
    p("Sources: vendor pricing pages (BrowserStack, TestMu, Sauce Labs, Firebase, AWS, Momentic) and third-party reports "
      "for NowSecure, gathered Nov 2026. \"—\" = not documented publicly.", SMALL),
    p("Moat we are building", H2),
    p("1. <b>Condition-specific failure data</b>: every run records which failures appear only under budget-phone or weak-network "
      "conditions — a dataset no global device cloud collects for India. 2. <b>Agent tests that learn the app</b>: tests are written "
      "from the app's own screens and the team's words, then re-run on every release. 3. <b>Workflow lock-in</b>: CI checks on every "
      "build, before/after scores and shareable reports become part of release sign-off."),
    p("Go-to-market", H2),
    p("Free tier for individual developers and student teams → paid seats for startups via GitHub/CI integration → agency "
      "packs. Channels: Android developer communities in India, college developer clubs, Play Store review-crisis content "
      "(\"we caught your ANR\"), and agency partnerships. First 90 days goal: 50 teams running weekly tests."),
    PageBreak(),
]

# ---------------- Page 3: unit economics + pricing ----------------
s += [
    p("Unit economics (measured inputs, stated assumptions)", H2),
    table([
        ["Cost item", "Input (verified price)", "Per full test run"],
        ["Device time", "Median run 3.9 min on one device; t3.medium $0.0416/hr (Mumbai). Today ~15 runs/hr on one "
         "host. Production host m8i.xlarge $0.212/hr ≈ 5–6 phones ≈ 80 runs/hr", "≈ ₹0.22–0.24"],
        ["AI explanations (8 findings)", "Sarvam 105B: ₹10 / 1M input, ₹25 / 1M output tokens; ~1.5k in + 0.3k out each", "≈ ₹0.18"],
        ["Agent-written tests (2 tests × 8 steps)", "~2k in + 0.1k out tokens per step", "≈ ₹0.36"],
        ["Planning / test writing", "1–2 short calls", "≈ ₹0.05"],
        ["<b>Total variable cost</b>", "excludes fixed hosting, storage, support", "<b>≈ ₹0.8–1 per run</b>"],
        ["Voice briefing (optional)", "Bulbul v3 TTS ₹3 / 1,000 chars; 60-s brief ≈ 900 chars", "≈ ₹2.7 per brief"],
        ["Voice conversation (optional)", "STT ₹0.49 / min + TTS; ~5-min chat", "≈ ₹7–8 per chat"],
        ["Fixed: always-on test host", "t3.medium 24×7 ≈ $30/mo; m8i.xlarge ≈ $155/mo", "₹2.6k–13k / mo"],
    ], [44 * mm, W - 44 * mm - 30 * mm, 30 * mm]),
    p("Assumes ₹85 per USD and excludes GST. Token counts are estimates from our prompts; device time is measured. Voice is "
      "optional and priced as an add-on so it never erodes core margin.", SMALL),
    p("Proposed pricing (to validate with 10–15 customer interviews)", H2),
    table([
        ["Plan", "Price / month", "Includes", "Est. variable cost", "Gross margin*"],
        ["Free", "₹0", "3 runs, 1 app, standard conditions", "≈ ₹3", "—"],
        ["Starter", "₹649", "30 runs, 2 apps, AI fixes, replay", "≈ ₹30", "≈ 95%"],
        ["Pro", "₹2,999", "200 runs, 5 apps, agent-written tests, CI, security checks, 20 voice briefs", "≈ ₹250", "≈ 92%"],
        ["Agency", "₹9,999", "1,000 runs, 20 client apps, white-label reports", "≈ ₹1,000", "≈ 90%"],
        ["Enterprise", "Custom", "Private test hosts, SSO, data residency, SLA", "dedicated host", "target 70%+"],
    ], [24 * mm, 25 * mm, W - 24 * mm - 25 * mm - 30 * mm - 24 * mm, 30 * mm, 24 * mm]),
    p("*Before fixed hosting, support and payment fees. Benchmarks: an India-only developer plan at ₹649/month (Cursor, 2026) "
      "shows INR + UPI pricing works; BrowserStack's comparable plans cost $99–225/month (≈ ₹8.4k–19k).", SMALL),
    p("Illustrative scenarios (not forecasts)", H2),
    table([
        ["Paying teams", "Plan mix", "Monthly revenue", "Annual run-rate"],
        ["100", "70 Starter · 25 Pro · 5 Agency", "≈ ₹1.7 lakh", "≈ ₹20 lakh"],
        ["1,000", "60% Starter · 32% Pro · 8% Agency", "≈ ₹21.5 lakh", "≈ ₹2.6 crore"],
        ["5,000", "50% Starter · 38% Pro · 12% Agency", "≈ ₹1.33 crore", "≈ ₹16 crore"],
    ], [26 * mm, 62 * mm, 36 * mm, W - 124 * mm]),
    PageBreak(),
]

# ---------------- Page 4: dashboard + judge Q&A + ask ----------------
s += [
    p("The dashboard we run the company on", H2),
    table([
        ["Metric", "Why it matters", "Today (22 Nov 2026)"],
        ["Activation: upload → first report", "Proves time-to-value", "Device run median 3.9 min"],
        ["Real-device coverage", "% of runs where the phone actually ran (not skipped)", "18 of 32 completed runs"],
        ["Critical issues per app", "Value delivered per test", "27 critical across 9 apps"],
        ["Fix rate (before/after)", "Customers improving = retention", "First case: F-Droid 28.6 → 42.1"],
        ["Weekly active teams / re-runs", "Habit + CI adoption", "Not yet measured (pre-launch)"],
        ["Free → paid conversion, CAC, payback", "Business health", "Not yet measured"],
        ["Gross margin per run", "Scales profitably", "≈ ₹0.8–1 cost vs ₹10–22 revenue per run"],
        ["Voice cost share", "Keep voice an add-on", "≈ ₹2.7 per briefing"],
    ], [52 * mm, 62 * mm, W - 114 * mm]),
    p("What judges and investors will ask — and our answers", H2),
]
qa = [
    ("Isn't this just BrowserStack?", "They rent device access, priced in dollars. We sell an answer: which issues will hurt "
     "Indian users and Play ranking, proven on budget-phone conditions, with fixes — in INR, self-serve, in minutes."),
    ("Is a container really a budget phone?", "No, and we say so. Memory cap and network are real; CPU slowness and heat "
     "are not simulated, and every report labels each condition Controlled / Approximated / Not simulated. Physical budget "
     "devices are on the roadmap for enterprise."),
    ("Why would they pay if Android vitals is free?", "Vitals tells you after users suffer. We catch it before release, explain "
     "the cause and the fix, and check it again on the next build."),
    ("Why a voice agent? Isn't it expensive?", "It is ≈ ₹2.7 per briefing and optional. Its job: brief non-technical "
     "founders/PMs in their language. The product works fully without it."),
    ("How do you scale?", "One host runs several Android containers; a run costs about ₹1 in variable cost. Scale = more hosts "
     "behind a job queue; the CI/CD and self-healing test lab already exist."),
    ("What about security of customer apps and passwords?", "APKs run only inside the isolated Android container; test-account "
     "passwords live in memory only, are masked everywhere, and the AI never sees them (verified by automated tests)."),
    ("What is the risk?", "Willingness to pay is unproven; we need 10–15 interviews and 50 weekly-active teams before raising. "
     "Fidelity versus physical phones must be benchmarked."),
]
for q, a in qa:
    s.append(KeepTogether([p(f"<b>{q}</b>", H3), p(a)]))
s += [
    p("Next 90 days", H2),
    p("Customer interviews (15) → free beta with 50 teams → GitHub/CI integration → UPI billing → first 10 paying teams. "
      "Engineering: job queue for parallel phones, physical budget-device pilot, fidelity benchmark versus real devices."),
]

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=13 * mm, bottomMargin=15 * mm,
                        title="BharatBench — Investor Brief", author="Team BrahMoss")
doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
