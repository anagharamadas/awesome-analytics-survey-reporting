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
import { api } from "./api";
import type { Survey } from "./types";

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
            <SurveySummary surveyId={selected} />
          )}
        </section>
      </div>
    </main>
  );
}

function SurveySummary({ surveyId }: { surveyId: number }) {
  // TODO: fetch /api/surveys/{surveyId}/summary and render the weekly table.
  return <p>TODO: summary for survey {surveyId}</p>;
}
