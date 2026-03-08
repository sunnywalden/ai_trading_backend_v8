from app.services.insight_service import (
    FAILED_POST_MORTEM_LESSON_SUMMARY,
    POST_MORTEM_CREATED_BY_JOB,
)


def test_failed_post_mortem_lesson_constants_match_repository_payload():
    assert POST_MORTEM_CREATED_BY_JOB == "post_mortem_service"
    assert (
        FAILED_POST_MORTEM_LESSON_SUMMARY
        == "Analysis generation failed. Review manually."
    )
