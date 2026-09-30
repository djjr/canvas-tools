"""Classic Quiz reads and the explicit manual-grading write."""
import re
from urllib.parse import urlparse
from canvas_core import CanvasError, CanvasTransport


def grading_status(detail, answer):
    # Do not combine contradictory markers from different representations.
    markers = [r['correct'] for r in (detail, answer) if 'correct' in r]
    def classify(marker):
        if marker == 'undefined':
            return 'ungraded'
        if type(marker) is bool or marker == 'defined':
            return 'graded'
        return 'unknown'
    states = {classify(m) for m in markers}
    return states.pop() if len(states) == 1 else 'unknown'


def parse_quiz(value, course, quiz, base):
    if value.strip():
        url = urlparse(value.strip())
        if (url.scheme, url.netloc) != (urlparse(base).scheme, urlparse(base).netloc):
            raise CanvasError('Quiz URL must belong to the configured Canvas site.')
        match = re.fullmatch(r'/courses/(\d+)/quizzes/(\d+)/?', url.path)
        if not match:
            raise CanvasError('Enter a Classic Quiz URL: /courses/123/quizzes/456.')
        return match.groups()
    if not re.fullmatch(r'[1-9]\d*', course or '') or not re.fullmatch(r'[1-9]\d*', quiz or ''):
        raise CanvasError('Enter a quiz URL or positive course and quiz IDs.')
    return course, quiz


def essay_records(questions, answers, person, attempt):
    """Essay-question grading state for one attempt, keyed by question id.
    Shared by the full load and single-submission verification so both see identical records."""
    answer_map = {str(a['id']): a for a in answers}
    # Match the attempt exactly; never reuse another attempt's response data.
    history = person.get('submission_history', [])
    snapshot = next((h for h in history if h.get('attempt') == attempt), None)
    if snapshot is None and person.get('attempt') == attempt:
        snapshot = person
    details = {str(a['question_id']): a for a in (snapshot or {}).get('submission_data', []) if isinstance(a, dict) and 'question_id' in a}
    records = {}
    for question in questions:
        if question.get('question_type') != 'essay_question':
            continue
        qid = str(question['id'])
        a, detail = answer_map.get(qid, {}), details.get(qid, {})
        records[qid] = {'question': question, 'answer': detail['text'] if 'text' in detail else a.get('answer'), 'available': 'text' in detail or 'answer' in a, 'score': detail.get('points', a.get('score')), 'grading_status': grading_status(detail, a), 'comment': detail.get('more_comments', a.get('comment'))}
    return records


class CanvasClient(CanvasTransport):
    def attempt_questions(self, root, submission, attempt):
        questions = self.pages(root + '/questions', params={'quiz_submission_id': submission, 'quiz_submission_attempt': attempt, 'per_page': 100})
        answers = self.pages(f'/api/v1/quiz_submissions/{submission}/questions', 'quiz_submission_questions', {'quiz_submission_attempt': attempt, 'include[]': 'quiz_question', 'per_page': 100})
        return questions, answers

    def load(self, course, quiz):
        root = f'/api/v1/courses/{course}/quizzes/{quiz}'
        metadata, _ = self.get(root)
        submissions = self.pages(root + '/submissions', 'quiz_submissions', {'include[]': ['user', 'submission'], 'per_page': 100})
        warnings, records, roster = [], [], []
        assignment = metadata.get('assignment_id')
        if assignment:
            try:
                roster = self.pages(f'/api/v1/courses/{course}/assignments/{assignment}/submissions', params={'include[]': ['user', 'submission_history'], 'per_page': 100})
            except CanvasError as error:
                warnings.append('Student roster and answer history: ' + str(error))
        roster_by_user = {r['user_id']: r for r in roster}
        for sub in submissions:
            attempt = sub.get('attempt')
            if not attempt:
                continue
            uid = sub['user_id']
            person = roster_by_user.get(uid, {})
            user = sub.get('user') or person.get('user') or {}
            state = 'excused' if person.get('excused') else sub.get('workflow_state', 'unknown')
            try:
                questions, answers = self.attempt_questions(root, sub['id'], attempt)
                for found in essay_records(questions, answers, person, attempt).values():
                    records.append({'submission_id': sub['id'], 'assignment_submission_id': sub.get('submission_id'), 'user_id': uid, 'name': user.get('name', f'Student {uid}'), 'attempt': attempt, 'state': state, **found, 'editable': found['available'] and state in ('complete', 'pending_review')})
            except CanvasError as error:
                warnings.append(f"Student {uid}, attempt {attempt}: {error}")
        represented = {s['user_id'] for s in submissions}
        absent = [{'name': (r.get('user') or {}).get('name', f"Student {r['user_id']}"), 'state': 'excused' if r.get('excused') else 'missing' if r.get('missing') or r.get('workflow_state') == 'unsubmitted' else r.get('workflow_state', 'unknown')} for r in roster if r['user_id'] not in represented]
        if not assignment:
            warnings.append('This quiz has no assignment roster. Students without a quiz submission cannot be listed.')
        return {'title': metadata.get('title', 'Canvas Quiz'), 'source': self.base, 'course': course, 'quiz': quiz, 'assignment': assignment, 'records': records, 'warnings': warnings, 'absent': absent}

    def load_submission(self, course, quiz, assignment, submission, attempt, user_id):
        """Refetch one submission's essay-question grading state. Used to verify a
        publish without reloading every other student, which is what made uploads slow.
        A failed roster lookup raises: the excused flag and answer history it carries
        are part of what verification checks."""
        person = {}
        if assignment:
            person, _ = self.get(f'/api/v1/courses/{course}/assignments/{assignment}/submissions/{user_id}', {'include[]': ['user', 'submission_history']})
        questions, answers = self.attempt_questions(f'/api/v1/courses/{course}/quizzes/{quiz}', submission, attempt)
        return bool(person.get('excused')), essay_records(questions, answers, person, attempt)

    def publish_question(self, course, quiz, submission, attempt, question, score, comment):
        """Only the Classic Quiz manual-grading endpoint; never submission-wide comments."""
        if not all(str(v).isdigit() and int(v) > 0 for v in (course, quiz, submission, attempt, question)):
            raise CanvasError('Invalid Canvas grading identifiers.')
        changes = {'score': float(score)}
        # Empty feedback means preserve Canvas feedback. Deletion is not supported.
        if comment.strip():
            changes['comment'] = comment
        self.put(f'/api/v1/courses/{course}/quizzes/{quiz}/submissions/{submission}', {'quiz_submissions': [{'attempt': int(attempt), 'questions': {str(question): changes}}]})
