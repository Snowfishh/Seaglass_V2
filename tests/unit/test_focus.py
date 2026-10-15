"""Question-focused selection: a named identifier draws in every record that carries it."""

from dataclasses import dataclass

from aspire_brain.platforms.focus import focus


@dataclass(frozen=True)
class Record:
    platform: str
    source_id: str
    text: str
    thread_id: str | None = None


QUESTION = "What is being done about processing payments in OPS-DEMO-01 and what remains missing?"
HANDOVER = Record("confluence", "page", "Workstream OPS-DEMO-01.\n\n"
                  "Five processing payments remain; the missing invoice is requested.")
ROOT = Record("slack", "root", "Handover for OPS-DEMO-01 is posted. Payments are processing.")
REPLY = Record("slack", "reply", "Two processing records now have partner references.",
               thread_id="root")
UNRELATED = Record("slack", "other", "Processing of leave requests is slower this week.")


def selected_ids(result):
    return [record.source_id for record, _ in result.selections]


def test_records_carrying_a_named_identifier_and_their_thread_replies_contribute():
    result = focus(QUESTION, [HANDOVER, ROOT, REPLY, UNRELATED])
    assert result.answerable
    assert {"page", "root", "reply"} <= set(selected_ids(result))
    # A record that shares only a common word, and no identifier or thread, is not drawn in.
    assert "other" not in selected_ids(result)


def test_a_reply_whose_root_is_not_permitted_is_not_anchored():
    # The root is absent (not permitted), so nothing links the reply to the identifier.
    result = focus(QUESTION, [HANDOVER, REPLY])
    assert "reply" not in selected_ids(result)


def test_a_time_is_not_an_identifier():
    result = focus("How many payments are processing in the 09:30 handover?",
                   [Record("confluence", "page", "The 09:30 handover lists 126 payments."),
                    Record("jira", "issue", "The 09:30 handover lists five payments processing."),
                    Record("slack", "msg", "Lunch at 09:30 tomorrow.")])
    assert "msg" not in selected_ids(result)


def test_a_first_paragraph_is_not_a_title():
    message = Record("slack", "msg", "Failover drill for the payment gateway is at 14:00.\n\n"
                     "Lunch is in the east kitchen today.\n\nParking passes expire on Friday.")
    result = focus("When is the payment gateway failover drill?", [message])
    assert result.subject_record_ids == []
    quoted = " ".join(sentence for _, sentences in result.selections for sentence in sentences)
    assert "Failover drill" in quoted
    assert "Lunch" not in quoted and "Parking" not in quoted


def test_a_heading_that_covers_the_question_makes_the_record_its_subject():
    page = Record("confluence", "runbook", "# Payment gateway failover runbook\n\n"
                  "Enable failover first.\n\nThen restart the service.")
    result = focus("Show the payment gateway failover runbook", [page])
    assert result.subject_record_ids == ["runbook"]
