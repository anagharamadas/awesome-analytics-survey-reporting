export type Survey = {
  survey_id: number;
  survey_name: string;
  client_name: string;
  invitations_sent: number;
};

/**
 * One row of GET /api/surveys/{id}/summary.
 *
 * These field names come straight from section A3 of the brief. If you decide
 * a field should be able to come back empty, change the type here to say so -
 * we read this file.
 *
 * ---
 *
 * Two fields are widened to `| null`, and both are deliberate.
 *
 * `completion_rate` is completed responses over *invitations sent*. Survey 9
 * ("Pilot - Do Not Report") has `invitations_sent = 0`, so the rate is not
 * zero, it is undefined. Returning 0 would put a wrong number on a client's
 * screen, which is worse than an honest blank. Typing it as `number` would
 * force the API to invent one.
 *
 * `median_duration_seconds` is null when no counted response in that week
 * recorded a duration. "Nobody reported a duration" and "everyone finished
 * instantly" are different facts and must not render identically.
 *
 * Making these nullable in the *type* is the point: `tsc` now refuses to
 * compile a table that renders either one without handling the null case, so
 * the bug cannot reach the page.
 *
 * `completion_rate` is a ratio in 0..1, not a percentage. The API does not
 * round it - formatting is this layer's job.
 */
export type WeekRow = {
  week_start: string;
  responses_started: number;
  responses_completed: number;
  completion_rate: number | null;
  median_duration_seconds: number | null;
};

/** The whole payload of GET /api/surveys/{id}/summary. */
export type SurveySummary = {
  survey_id: number;
  survey_name: string;
  client_name: string;
  invitations_sent: number;
  weeks: WeekRow[];
};
