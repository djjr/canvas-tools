"""Classic Quiz publishing: one manual-grading write per question, on the shared journaled flow."""
from decimal import Decimal
from publishing_core import JournaledPublisher, draft_version  # noqa: F401 (draft_version re-exported)
from quiz import fingerprint


def matches(record, item):
    try:
        return (record.get('grading_status') == 'graded'
                and Decimal(str(record['score'])) == Decimal(item['draft']['score'])
                and (not item['draft']['comment'].strip() or record['comment'] == item['draft']['comment']))
    except (ValueError, TypeError, ArithmeticError):
        return False


class Publisher(JournaledPublisher):
    kind = 'quiz'

    def refresh(self, data, record):
        """Current Canvas state for exactly one record. Scoped to one submission
        instead of a full-quiz reload, since callers only ever look up one identity."""
        excused, records = self.client.load_submission(data['course'], data['quiz'], data.get('assignment'), record['submission_id'], record['attempt'], record['user_id'])
        fresh = records.get(str(record['question']['id']))
        if not fresh:
            return None
        state = 'excused' if excused else record['state']
        current = {**record, **fresh, 'state': state, 'editable': fresh['available'] and state in ('complete', 'pending_review')}
        current['fingerprint'] = fingerprint(current)
        return current

    def write(self, data, record, draft):
        self.client.publish_question(data['course'], data['quiz'], record['submission_id'], record['attempt'], record['question']['id'], draft['score'], draft['comment'])

    def verified(self, current, item):
        return matches(current, item)

    def maximum(self, record):
        return Decimal(str(record['question']['points_possible'])) + 1
