"""End-to-end HTTP timing for /summary, which is what the client actually
feels when they click a survey. Includes FastAPI, Pydantic validation, JSON
serialisation and the network hop - not just the SQL."""
import json, statistics, time, urllib.request

SURVEYS = list(range(1, 13))
ROUNDS = 20

# Warm up: first call pays for connection setup and Postgres plan caching,
# which the client only pays once. Excluded deliberately, and said out loud.
for s in SURVEYS:
    urllib.request.urlopen(f"http://localhost:8000/api/surveys/{s}/summary").read()

per_survey = {}
allt = []
for s in SURVEYS:
    ts = []
    url = f"http://localhost:8000/api/surveys/{s}/summary"
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        urllib.request.urlopen(url).read()
        ts.append((time.perf_counter() - t0) * 1000)
    per_survey[s] = ts
    allt += ts

print(f"{ROUNDS} requests x {len(SURVEYS)} surveys = {len(allt)} samples\n")
print(f"{'survey':>6} {'rows':>6} {'p50':>8} {'p95':>8} {'max':>8}")
rows = {}
for s in SURVEYS:
    n = len(json.load(urllib.request.urlopen(
        f"http://localhost:8000/api/surveys/{s}/summary"))["weeks"])
    ts = sorted(per_survey[s])
    print(f"{s:>6} {n:>6} {statistics.median(ts):>7.1f}ms "
          f"{ts[int(len(ts)*0.95)-1]:>7.1f}ms {max(ts):>7.1f}ms")

allt.sort()
print(f"\nACROSS ALL SURVEYS")
print(f"  p50 {statistics.median(allt):.1f} ms")
print(f"  p95 {allt[int(len(allt)*0.95)-1]:.1f} ms")
print(f"  p99 {allt[int(len(allt)*0.99)-1]:.1f} ms")
print(f"  max {max(allt):.1f} ms")
print(f"\n  budget 300 ms -> {'PASS' if max(allt) < 300 else 'FAIL'} "
      f"(worst single request {max(allt):.1f} ms, "
      f"{300/max(allt):.1f}x headroom)")
