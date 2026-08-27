# Review — PR #412, `feat/response-export`

**Block.** Findings 1–4 are the blockers: authentication is switched off, the
export is injectable, the delete reports success when it has failed, and the
list page renders unsanitised HTML. Finding 5 is not a security issue but
writes wrong data into the audit table, so it belongs in the same pass.

A note on the description, because it is doing a lot of work: *"tests pass"*
is not evidence here. `test_export_returns_responses` asserts the response is
a list, which `[]` satisfies. `test_close_survey_increments_close_count` never
reads `close_count`. And `test_delete_survey` asserts `200` for a survey that
does not exist — it pins finding 3's bug in place as expected behaviour. All
three would still pass with the endpoint bodies deleted. That is worth knowing
for its own sake: a suite that cannot fail is not protecting you.

None of this is a criticism of using Cursor. The generated code is
structurally reasonable. What it cannot do is know that this service holds a
customer's compliance-critical survey data, and that is the part of the review
that has to come from you.

---

### 1. Authentication is disabled, and the production signing secret is in the repo
`review_this.py:24, 29`

`jwt.decode(token, options={"verify_signature": False})` accepts any
well-formed JWT without checking it was signed by us. Anyone can base64 a
`{"sub": "1"}` payload and become user 1 — or any user — which makes every
other endpoint in this PR unauthenticated, including the delete. Separately,
`JWT_SECRET = "aa-prod-2026-8f3d91c4b7e2"` is a live production secret now in
git history; it must be rotated regardless of what happens to this PR, because
rotating is the only thing that undoes a commit.

Decode with the secret and an explicit algorithm allow-list
(`jwt.decode(token, JWT_SECRET, algorithms=["HS256"])`), load the secret from
the environment, and catch `InvalidTokenError` into a 401. Pin the algorithm
list explicitly — omitting it is how `alg: none` attacks get in.

### 2. `delete_survey` swallows every error and reports success anyway
`review_this.py:94–100`

`except Exception: pass` followed by an unconditional
`return {"deleted": survey_id}` means a failed delete is indistinguishable
from a successful one. On this product that is not an ordinary bug: the
compliance requirement is that a deleted survey's responses are *gone
permanently*, and this endpoint will tell the client they are while the rows
are still there. It also never checks the survey exists (so `DELETE /999`
returns `200 {"deleted": 999}`), never checks the caller is allowed to delete
it, and leaves the session un-rolled-back for whatever runs next on it.

Drop the try/except so a failure surfaces as a 500, 404 when the survey is not
found, add the authorisation check, and let the transaction roll back. If the
delete genuinely needs to tolerate partial failure, that is a design
conversation, not a bare `except`.

### 3. SQL injection in the export via `sort_by` and `order`
`review_this.py:46–51`

`sort_by` and `order` are `str` query parameters interpolated straight into
the SQL. `?sort_by=id;DROP TABLE responses--` executes. With finding 1 in
place this is reachable without credentials, so it is arbitrary SQL against
production from the open internet.

Column and direction cannot be bound as parameters, so validate them against
an allow-list of real column names and `{"asc", "desc"}`, and reject anything
else with a 422. While you are in there, `limit` is unbounded — `limit=10000000`
is a denial-of-service — so clamp it, and replace `SELECT *` with the columns
you actually use so a future schema change cannot start leaking a new column.

### 4. Stored XSS on the list page
`ReviewThis.tsx:52`

`dangerouslySetInnerHTML={{ __html: surveys[0]?.description }}` injects a
survey description into the DOM as live HTML. Descriptions are user-supplied,
so anyone who can name a survey can run script in every other user's browser
on this page — session tokens included.

Render it as text (`<div className="prose mt-4">{surveys[0]?.description}</div>`).
If descriptions genuinely need formatting, sanitise with DOMPurify against a
narrow allow-list, and do it server-side on write so the stored value is the
safe one.

### 5. `build_audit` has two default-argument bugs that silently corrupt the audit trail
`review_this.py:103`

`meta: dict = {}` is evaluated once at import, and line 104 mutates it — so
every call without an explicit `meta` shares and accumulates the previous
call's keys. `at: datetime = datetime.utcnow()` is also evaluated once at
import, so every audit event is stamped with the process start time rather
than the time it happened. Both are silent: nothing raises, the rows just
become wrong. This is the table the client reconciles historical counts
against at year end, which is the worst possible place for quietly wrong
timestamps.

Use `meta: dict | None = None` with `meta = dict(meta or {})` inside, and
`at: datetime | None = None` with `at = at or datetime.now(timezone.utc)`.
Use `datetime.now(timezone.utc)` rather than `utcnow()` throughout —
`utcnow()` returns a naive datetime and is deprecated in 3.12.

---

## One thing that is fine

**The `{survey_id}` interpolation on line 48 is not a vulnerability**, even
though it is the line that looks most alarming in the file.

`survey_id` is declared `survey_id: int` as a path parameter, so FastAPI
coerces and validates it before the function body runs — `/api/surveys/1;DROP
TABLE/export` never reaches the query, it returns a 422. The exploitable
injection in this endpoint is `sort_by` and `order` (finding 3), which are
`str` and validated by nothing.

I would still bind it as a parameter, because "safe because of a type
annotation three lines up" is a property someone can delete by accident. But
if you fix only one thing in that query, fix the two that are actually
reachable. Worth internalising the general shape: *typed path parameters are
validated, query-string strings are not.*

---

## Not blocking, worth a follow-up issue rather than this PR

The `async def` endpoints all make blocking synchronous calls (SQLAlchemy, and
a 30-second `requests.post`) directly on the event loop, so one slow export
stalls every other request in the process. `close_count = close_count + 1` is
a read-modify-write race that loses concurrent updates. The export does an
N+1 `db.query(Survey).get()` per row. `avgCompletion` divides by
`surveys.length`, which renders `NaN%` on first paint before the fetch
resolves. The `useEffect` dependency array is empty while the fetch reads
`orgId` and `query`, so it never refetches. And `handleDelete` removes the row
from state without awaiting the request or confirming a destructive action.

I have deliberately not ranked these among the five. They are real, and I would
take them — but fixing them changes nothing about whether this can go to `main`,
and a review that lists fifteen things at equal weight gives you no way to tell
which four actually stop the merge.
