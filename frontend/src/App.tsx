/**
 * The one page.
 *
 * What is here: the shell, and a survey list that calls the API and handles
 * its own loading and error states. Use it as the pattern, or replace it.
 *
 * What is not here: the weekly summary table. That is section A4 of the brief,
 * and so is the delete. Loading and error states for those are graded.
 */

import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { Survey, SurveySummary, WeekRow } from "./types";

export function App() {
  const [surveys, setSurveys] = useState<Survey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Survey[]>("/api/surveys")
      .then((data) => !cancelled && setSurveys(data))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Survey reporting</h1>
      <div className="layout">
        <section>
          <h2>Surveys</h2>
          {error && <p className="error">Could not load surveys: {error}</p>}
          {!error && surveys === null && <p>Loading...</p>}
          {surveys?.length === 0 && <p>No surveys. Have you run the ingest?</p>}
          <ul>
            {surveys?.map((s) => (
              <li key={s.survey_id}>
                <button onClick={() => setSelected(s.survey_id)}>
                  {s.survey_name}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2>Weekly summary</h2>
          {selected === null ? (
            <p>Pick a survey.</p>
          ) : (
            /**
             * `key` remounts the component when the selection changes, so its
             * state starts clean. Without it, switching surveys leaves the
             * previous survey's table on screen under the new heading until
             * the fetch resolves - a wrong number attributed to the wrong
             * survey, which is the worst kind of stale render.
             */
            <SurveySummaryPanel key={selected} surveyId={selected} />
          )}
        </section>
      </div>
    </main>
  );
}

/** Ratio in 0..1 from the API -> a percentage a person can read. */
function formatCompletionRate(rate: number | null): string {
  // Null means the survey has zero invitations, so the rate is undefined
  // rather than zero. Survey 9 is exactly this case.
  if (rate === null) return "-";
  return `${(rate * 100).toFixed(2)}%`;
}

/** Seconds -> "12m 34s". */
function formatDuration(seconds: number | null): string {
  // Note `=== null`, not `!seconds`: a genuine median of 0 seconds is falsy
  // and would otherwise render as "no data".
  if (seconds === null) return "-";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function SurveySummaryPanel({ surveyId }: { surveyId: number }) {
  const [summary, setSummary] = useState<SurveySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped by the retry button to re-run the effect.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Reset on every attempt so a retry after a failure shows the loading
    // state again rather than the old error next to fresh data.
    setSummary(null);
    setError(null);

    api<SurveySummary>(`/api/surveys/${surveyId}/summary`)
      .then((data) => !cancelled && setSummary(data))
      .catch((e) => {
        if (cancelled) return;
        // A 404 is a different thing from "the server is down", and the API
        // deliberately distinguishes them. Say which one happened.
        setError(
          e instanceof ApiError && e.status === 404
            ? "That survey no longer exists. It may have been deleted."
            : String(e)
        );
      });

    // Guards against a slow response for survey A landing after the user has
    // already clicked survey B and overwriting it.
    return () => {
      cancelled = true;
    };
  }, [surveyId, attempt]);

  // Same three states, in the same order, as the survey list above.
  if (error) {
    return (
      <>
        <p className="error">Could not load summary: {error}</p>
        <button onClick={() => setAttempt((n) => n + 1)}>Retry</button>
      </>
    );
  }
  if (summary === null) return <p>Loading...</p>;

  return (
    <>
      <p>
        <strong>{summary.survey_name}</strong> - {summary.client_name} -{" "}
        {summary.invitations_sent.toLocaleString()} invitations sent
      </p>

      {summary.weeks.length === 0 ? (
        /**
         * Survey 9 ("Pilot - Do Not Report") has zero responses AND zero
         * invitations. An empty table body would read as a broken page, so
         * this says which of the two it is. The brief requires every survey
         * in the list to survive, not just the ones with data.
         */
        <p>
          No responses recorded for this survey yet, so there is nothing to
          report by week.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Week starting (Sat)</th>
              <th>Responses</th>
              <th>Completed</th>
              <th>Completion rate</th>
              <th>Median duration</th>
            </tr>
          </thead>
          <tbody>
            {summary.weeks.map((week: WeekRow) => (
              // Keyed on week_start, not the array index. The index is
              // positional, so it re-associates rows with different data when
              // the list changes - React then reuses the wrong DOM node.
              <tr key={week.week_start}>
                <td>{week.week_start}</td>
                <td>{week.responses_started}</td>
                <td>{week.responses_completed}</td>
                <td title={
                  week.completion_rate === null
                    ? "Undefined: this survey has zero invitations sent"
                    : `${week.responses_completed} completed of ${summary.invitations_sent} invitations sent`
                }>
                  {formatCompletionRate(week.completion_rate)}
                </td>
                <td title={
                  week.median_duration_seconds === null
                    ? "No counted response that week recorded a duration"
                    : `${week.median_duration_seconds} seconds`
                }>
                  {formatDuration(week.median_duration_seconds)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p>
        <small>
          Responses counts completed and partial responses. Abandoned and
          started responses count in neither column. Completion rate is
          completed responses over invitations sent for the whole survey.
        </small>
      </p>
    </>
  );
}
