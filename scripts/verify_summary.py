"""Recompute a survey's summary from the CSV and diff it against the API.

    python3 scripts/verify_summary.py 5        # one survey
    for s in $(seq 1 12); do python3 scripts/verify_summary.py $s; done

The brief's Step 4 says: "you have read your own output back against all four
rules line by line". This is that, automated.

The point is that it shares NO code with the endpoint. The SQL buckets weeks
with date_trunc('week', ts + '2 days') - '2 days'; this walks backwards to the
most recent Saturday with Python's weekday(). Two independent implementations
of the same rule agreeing is real evidence. One implementation agreeing with
itself is not.

It also re-derives the validation and duplicate-resolution rules from scratch,
so a bug in the ingest that dropped or kept the wrong row would show up as a
week-count or count mismatch rather than passing silently."""
import csv, json, math, statistics, sys, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
EMPTY = {"", "n/a", "null", "-", "none"}
RANK = {"completed": 3, "partial": 2, "started": 1, "abandoned": 0}

def clean(v):
    v = v.strip()
    return None if v.casefold() in EMPTY else v

def dt(v):
    v = clean(v)
    return None if v is None else datetime.strptime(v, "%d/%m/%Y %H:%M:%S").replace(tzinfo=IST)

def week_start(d):
    """Saturday-to-Friday week, computed a completely different way from the
    SQL: walk backwards to the most recent Saturday. Python weekday(): Sat=5."""
    local = d.astimezone(IST)
    return (local.date() - timedelta(days=(local.weekday() - 5) % 7))

SURVEY_ID = int(sys.argv[1])
invitations = {int(r["survey_id"]): int(r["invitations_sent"])
               for r in csv.DictReader(open("data/surveys.csv", encoding="utf-8-sig"))}
known = set(invitations)

rows = list(csv.DictReader(open("data/responses.csv", encoding="utf-8-sig")))

# --- replicate validation + dedupe, independently ---
seen_ids, good = set(), []
for r in rows:
    try:
        rid, sid = int(r["response_id"]), int(r["survey_id"])
        if sid not in known: continue
        email = clean(r["respondent_email"])
        if not email or "@" not in email or " " in email.strip(): continue
        email = email.lower()
        started, completed = dt(r["started_at"]), dt(r["completed_at"])
        if started is None: continue
        status = clean(r["status"]).lower()
        rating = clean(r["rating"])
        rating = int(rating) if rating else None
        if rating is not None and not 1 <= rating <= 5: continue
        dur = clean(r["duration_seconds"])
        dur = int(dur.replace(",", "")) if dur else None
        if dur is not None and dur < 0: continue
        if completed and completed < started: continue
        if status == "completed" and completed is None: continue
        if status in ("started", "abandoned") and completed is not None: continue
    except (ValueError, AttributeError):
        continue
    if rid in seen_ids: continue
    seen_ids.add(rid)
    good.append({"rid": rid, "sid": sid, "email": email, "status": status,
                 "started": started, "dur": dur})

groups = {}
for g in good:
    groups.setdefault((g["sid"], g["email"]), []).append(g)
winners = [max(v, key=lambda x: (RANK[x["status"]], x["started"], x["rid"])) for v in groups.values()]

# --- build the summary ---
weeks = {}
for w in winners:
    if w["sid"] != SURVEY_ID or w["status"] not in ("completed", "partial"): continue
    weeks.setdefault(week_start(w["started"]), []).append(w)

inv = invitations[SURVEY_ID]
mine = []
for ws in sorted(weeks):
    grp = weeks[ws]
    durs = sorted(x["dur"] for x in grp if x["dur"] is not None)
    comp = sum(1 for x in grp if x["status"] == "completed")
    mine.append({
        "week_start": ws.isoformat(),
        "responses_started": len(grp),
        "responses_completed": comp,
        "completion_rate": comp / inv if inv else None,
        "median_duration_seconds": math.floor(statistics.median(durs) + 0.5) if durs else None,
    })

api = json.load(urllib.request.urlopen(f"http://localhost:8000/api/surveys/{SURVEY_ID}/summary"))["weeks"]

print(f"survey {SURVEY_ID}: python weeks={len(mine)}  api weeks={len(api)}")
bad = 0
for m, a in zip(mine, api):
    if m != a:
        bad += 1
        print("  MISMATCH\n    python:", m, "\n    api   :", a)
if len(mine) != len(api):
    bad += 1
    print("  WEEK COUNT MISMATCH")
    pm, pa = {w["week_start"] for w in mine}, {w["week_start"] for w in api}
    print("   only in python:", sorted(pm - pa), "\n   only in api:", sorted(pa - pm))

# rule 1: every week_start really is a Saturday
notsat = [w["week_start"] for w in api
          if datetime.fromisoformat(w["week_start"]).weekday() != 5]
print(f"  rule 1 Saturday starts: {'OK' if not notsat else 'FAIL ' + str(notsat)}")
print(f"  rule 2 rate=completed/invitations: "
      f"{'OK' if all(w['completion_rate'] is None or abs(w['completion_rate'] - w['responses_completed']/inv) < 1e-9 for w in api) else 'FAIL'}")
print(f"  rule 3 completed <= started-count: "
      f"{'OK' if all(w['responses_completed'] <= w['responses_started'] for w in api) else 'FAIL'}")
print("  RESULT:", "IDENTICAL" if bad == 0 else f"{bad} MISMATCHES")
