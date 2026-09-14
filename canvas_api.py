"""Canvas reads and an explicit manual-grading write. Credentials stay at the configured origin."""
import re
from urllib.parse import urlparse, urljoin
import requests

class CanvasError(Exception):
    pass

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

class CanvasClient:
    def __init__(self, base, token, session=None):
        p = urlparse(base)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
            raise CanvasError('CANVAS_BASE_URL must be an HTTPS site origin.')
        if not token:
            raise CanvasError('Create the local .env file with CANVAS_BASE_URL and CANVAS_TOKEN first.')
        self.base, self.token = base.rstrip('/'), token
        self.session = session or requests.Session()

    def get(self, path, params=None):
        url = urljoin(self.base, path)
        p, base = urlparse(url), urlparse(self.base)
        if (p.scheme, p.netloc) != (base.scheme, base.netloc) or not p.path.startswith('/api/v1/'):
            raise CanvasError('Canvas returned an unsafe pagination URL; retrieval stopped.')
        try:
            response = self.session.get(url, params=params, headers={'Authorization': f'Bearer {self.token}'}, timeout=(10, 40), allow_redirects=False)
            if response.status_code != 200:
                messages = {401: 'Canvas authentication failed. Check your local token.', 403: 'Canvas denied access. Check course permissions and quiz settings.', 404: 'Canvas could not find this resource.', 429: 'Canvas rate limit reached. Wait a moment, then reload.'}
                raise CanvasError(messages.get(response.status_code, f'Canvas request failed (HTTP {response.status_code}). Try again later.'))
            return response.json(), response.links.get('next', {}).get('url')
        except (requests.RequestException, ValueError):
            raise CanvasError('Canvas connection timed out, failed, or returned invalid data. Check the site and try again.') from None

    def pages(self, path, key=None, params=None):
        result, seen = [], set()
        while path:
            if path in seen:
                raise CanvasError('Canvas pagination repeated a page; retrieval stopped.')
            seen.add(path)
            data, next_path = self.get(path, params)
            rows = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise CanvasError('Canvas returned an unexpected list format.')
            result.extend(rows)
            path, params = next_path, None
        return result

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
                questions = self.pages(root + '/questions', params={'quiz_submission_id': sub['id'], 'quiz_submission_attempt': attempt, 'per_page': 100})
                answers = self.pages(f"/api/v1/quiz_submissions/{sub['id']}/questions", 'quiz_submission_questions', {'quiz_submission_attempt': attempt, 'include[]': 'quiz_question', 'per_page': 100})
                answer_map = {str(a['id']): a for a in answers}
                # Match the attempt exactly; never reuse another attempt's response data.
                history = person.get('submission_history', [])
                snapshot = next((h for h in history if h.get('attempt') == attempt), None)
                if snapshot is None and person.get('attempt') == attempt:
                    snapshot = person
                details = {str(a['question_id']): a for a in (snapshot or {}).get('submission_data', []) if isinstance(a, dict) and 'question_id' in a}
                for question in questions:
                    if question.get('question_type') != 'essay_question':
                        continue
                    qid = str(question['id'])
                    a, detail = answer_map.get(qid, {}), details.get(qid, {})
                    available = 'text' in detail or 'answer' in a
                    answer = detail['text'] if 'text' in detail else a.get('answer')
                    records.append({'submission_id': sub['id'], 'assignment_submission_id': sub.get('submission_id'), 'user_id': uid, 'name': user.get('name', f'Student {uid}'), 'attempt': attempt, 'state': state, 'question': question, 'answer': answer, 'available': available, 'score': detail.get('points', a.get('score')), 'grading_status': grading_status(detail, a), 'comment': detail.get('more_comments', a.get('comment')), 'editable': available and state in ('complete', 'pending_review')})
            except CanvasError as error:
                warnings.append(f"Student {uid}, attempt {attempt}: {error}")
        represented = {s['user_id'] for s in submissions}
        absent = [{'name': (r.get('user') or {}).get('name', f"Student {r['user_id']}"), 'state': 'excused' if r.get('excused') else 'missing' if r.get('missing') or r.get('workflow_state') == 'unsubmitted' else r.get('workflow_state', 'unknown')} for r in roster if r['user_id'] not in represented]
        if not assignment:
            warnings.append('This quiz has no assignment roster. Students without a quiz submission cannot be listed.')
        return {'title': metadata.get('title', 'Canvas Quiz'), 'source': self.base, 'course': course, 'quiz': quiz, 'assignment': assignment, 'records': records, 'warnings': warnings, 'absent': absent}

    def load_submission(self, course, quiz, assignment, submission, attempt, user_id):
        """Refetch one submission's essay-question grading state. Used to verify a
        publish without reloading every other student, which is what made uploads slow."""
        root = f'/api/v1/courses/{course}/quizzes/{quiz}'
        person = {}
        if assignment:
            try:
                person, _ = self.get(f'/api/v1/courses/{course}/assignments/{assignment}/submissions/{user_id}', {'include[]': ['user', 'submission_history']})
            except CanvasError:
                person = {}
        questions = self.pages(root + '/questions', params={'quiz_submission_id': submission, 'quiz_submission_attempt': attempt, 'per_page': 100})
        answers = self.pages(f'/api/v1/quiz_submissions/{submission}/questions', 'quiz_submission_questions', {'quiz_submission_attempt': attempt, 'include[]': 'quiz_question', 'per_page': 100})
        answer_map = {str(a['id']): a for a in answers}
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
            available = 'text' in detail or 'answer' in a
            answer = detail['text'] if 'text' in detail else a.get('answer')
            records[qid] = {'question': question, 'answer': answer, 'available': available, 'score': detail.get('points', a.get('score')), 'grading_status': grading_status(detail, a), 'comment': detail.get('more_comments', a.get('comment'))}
        return bool(person.get('excused')), records

    def publish_question(self, course, quiz, submission, attempt, question, score, comment):
        """Only the Classic Quiz manual-grading endpoint; never submission-wide comments."""
        if not all(str(v).isdigit() and int(v) > 0 for v in (course, quiz, submission, attempt, question)):
            raise CanvasError('Invalid Canvas grading identifiers.')
        changes = {'score': float(score)}
        # Empty feedback means preserve Canvas feedback. Deletion is not supported.
        if comment.strip():
            changes['comment'] = comment
        payload = {'quiz_submissions': [{'attempt': int(attempt), 'questions': {str(question): changes}}]}
        url = f'{self.base}/api/v1/courses/{course}/quizzes/{quiz}/submissions/{submission}'
        try:
            response = self.session.put(url, json=payload, headers={'Authorization': f'Bearer {self.token}'}, timeout=(10,40), allow_redirects=False)
            if response.status_code != 200:
                raise CanvasError(f'Canvas upload returned HTTP {response.status_code}. Verify the result in Canvas before retrying.')
        except requests.RequestException:
            raise CanvasError('Upload connection failed. Its outcome is uncertain; verify in Canvas before retrying.') from None
