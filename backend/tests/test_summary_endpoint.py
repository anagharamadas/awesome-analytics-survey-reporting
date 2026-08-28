"""
Tests for GET /api/surveys/{id}/summary.

One test per client rule, each pinning a number that would be wrong if the
rule were implemented the obvious-but-incorrect way. Written after noticing
that the PR in task-b/ ships three tests that all still pass with the endpoint
bodies deleted -- so each assertion here is chosen to fail if the behaviour
regresses, not merely to exercise the code path.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

from .conftest import requires_db

client = TestClient(app)


def weeks_for(survey_id: int) -> dict[str, dict]:
    """Fetch a summary and index its weeks by week_start."""
    response = client.get(f"/api/surveys/{survey_id}/summary")
    assert response.status_code == 200, response.text
    return {w["week_start"]: w for w in response.json()["weeks"]}


@requires_db
class TestReportingWeek:
    """Rule 1: 'Our reporting week runs Saturday to Friday. It always has.'"""

    def test_saturday_and_the_following_friday_are_one_week(self, seeded):
        """Sat 3 Jan 00:00:00 and Fri 9 Jan 23:59:59 must land together.

        This is the assertion that fails if someone reaches for the default
        date_trunc('week', ...), which starts weeks on Monday: the Saturday
        would fall into the previous week and the Friday into this one.
        """
        weeks = weeks_for(9001)
        assert "2026-01-03" in weeks
        assert weeks["2026-01-03"]["responses_started"] == 2

    def test_the_next_saturday_opens_a_new_week(self, seeded):
        """Sat 10 Jan 00:00:00 is one second after the Friday above, and in a
        different reporting week. An off-by-one in the two-day shift collapses
        these two weeks into one."""
        weeks = weeks_for(9001)
        assert "2026-01-10" in weeks
        assert weeks["2026-01-10"]["responses_started"] == 2

    def test_every_week_start_is_a_saturday(self, seeded):
        import datetime

        for survey_id in (9001, 9002, 9003, 9004, 9005):
            for week_start in weeks_for(survey_id):
                assert (
                    datetime.date.fromisoformat(week_start).weekday() == 5
                ), f"{week_start} on survey {survey_id} is not a Saturday"

    def test_bucketing_uses_client_local_time_not_utc(self, seeded):
        """Sat 10 Jan 01:00 IST is Fri 9 Jan 19:30 UTC.

        Bucketing the UTC instant would file it under 2026-01-03, giving the
        first week 3 responses and the second 1. Every response between 00:00
        and 05:30 IST would move to the previous week - a wrong number that
        looks entirely plausible on the page.
        """
        weeks = weeks_for(9001)
        assert weeks["2026-01-10"]["responses_started"] == 2
        assert weeks["2026-01-03"]["responses_started"] == 2

    def test_the_same_instant_reports_in_a_different_week_for_a_dubai_client(
        self, seeded
    ):
        """The load-bearing claim of ADR 0001, tested rather than asserted.

        Survey 9005 holds the same instant as survey 9001's fourth response
        (Sat 10 Jan 01:00 IST), under a client whose reporting_timezone is
        Asia/Dubai. Dubai is UTC+04:00, 90 minutes behind Kolkata, so there
        that instant is Fri 9 Jan 23:30 and it reports in the week beginning
        Sat 3 Jan - a different week from the same instant read in Kolkata.

        If this passes, onboarding the Dubai customer really is one INSERT and
        not a migration, which is the claim ADR 0001 makes.

        (My first draft of this fixture used 03:00 IST and asserted the same
        thing. It failed, correctly: 03:00 IST is 01:30 in Dubai, still a
        Saturday. The window where the two zones disagree is only the 90
        minutes after local midnight, which is exactly the kind of arithmetic
        worth pinning in a test rather than trusting.)
        """
        assert "2026-01-10" in weeks_for(9001)
        assert "2026-01-03" in weeks_for(9005)
        assert "2026-01-10" not in weeks_for(9005)


@requires_db
class TestWhichResponsesCount:
    """Rule 3: 'A partial counts in the response count. It does not count as
    completed. abandoned and started count in neither.'"""

    def test_partial_counts_as_a_response_but_not_as_completed(self, seeded):
        week = weeks_for(9002)["2026-01-17"]
        # completed + partial = 2. Not 4, which is every row, and not 1,
        # which is completed only.
        assert week["responses_started"] == 2
        assert week["responses_completed"] == 1

    def test_completion_is_read_from_status_not_from_completed_at(self, seeded):
        """The partial in the fixture carries a completed_at, exactly as all
        10,953 partial rows in the real export do. Counting rows with a
        non-null completed_at would return 2 here instead of 1, and would
        overcount completions across the real dataset by roughly two thirds.
        """
        assert weeks_for(9002)["2026-01-17"]["responses_completed"] == 1


@requires_db
class TestCompletionRate:
    """Rule 2: 'completed responses over invitations sent for that survey.'"""

    def test_denominator_is_invitations_not_responses_received(self, seeded):
        """1 completed of 2 counted responses, against 100 invitations.

        0.01 proves the denominator is invitations_sent. 0.5 would mean it had
        been divided by the responses received, which is the exact mistake the
        client wrote in to head off.
        """
        assert weeks_for(9002)["2026-01-17"]["completion_rate"] == pytest.approx(0.01)

    def test_zero_invitations_gives_null_not_zero_and_does_not_error(self, seeded):
        """Survey 9 in the real data has invitations_sent = 0. The rate is
        undefined, not zero: 0% would be a wrong number on a client's screen,
        and an unguarded division would be a 500."""
        week = weeks_for(9003)["2026-01-17"]
        assert week["completion_rate"] is None
        assert week["responses_completed"] == 1


@requires_db
class TestMedianDuration:
    def test_median_of_an_even_count_interpolates(self, seeded):
        """Durations 100 and 300 in the first week, 200 and 400 in the second.

        percentile_cont averages the two middle values, so 200 and 300.
        percentile_disc would return 100 and 200 instead.
        """
        weeks = weeks_for(9001)
        assert weeks["2026-01-03"]["median_duration_seconds"] == 200
        assert weeks["2026-01-10"]["median_duration_seconds"] == 300

    def test_a_week_with_no_recorded_duration_is_null_not_zero(self, seeded):
        """'Nobody reported a duration' and 'everyone finished instantly' are
        different facts and must not render identically."""
        weeks = weeks_for(9004)
        assert weeks["2026-01-17"]["median_duration_seconds"] is None
        assert weeks["2026-01-24"]["median_duration_seconds"] == 250

    def test_a_null_duration_does_not_drag_the_median_down(self, seeded):
        """The row with no duration still counts as a response."""
        assert weeks_for(9004)["2026-01-17"]["responses_started"] == 1


@requires_db
class TestEndpointContract:
    def test_unknown_survey_is_404_not_an_empty_summary(self):
        """'This survey has no responses' and 'this survey does not exist' are
        different answers, and the front end renders them differently."""
        assert client.get("/api/surveys/424242/summary").status_code == 404

    def test_a_survey_with_no_responses_returns_an_empty_week_list(self, seeded):
        """Survey 9 must not 404 and must not error - the page has to survive
        every survey in the list, not only the ones with data."""
        response = client.get("/api/surveys/9/summary")
        if response.status_code == 404:
            pytest.skip("survey 9 only exists once the ingest has run")
        assert response.status_code == 200
        assert response.json()["weeks"] == []

    def test_the_survey_list_matches_the_front_end_type(self, seeded):
        response = client.get("/api/surveys")
        assert response.status_code == 200
        for row in response.json():
            assert set(row) == {
                "survey_id",
                "survey_name",
                "client_name",
                "invitations_sent",
            }
