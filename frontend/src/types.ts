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
 */
export type WeekRow = {
  week_start: string;
  responses_started: number;
  responses_completed: number;
  completion_rate: number;
  median_duration_seconds: number;
};
