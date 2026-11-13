"""Markdown export of student responses, shared by every grading mode.

Exports are built from the local snapshot only; they never contact Canvas.
Student names are replaced by stable pseudonyms unless names are requested.
"""
import hashlib
import re
from datetime import date
from html.parser import HTMLParser

_BLOCKS = {'p', 'div', 'section', 'article', 'table', 'tr', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
_SKIP = {'script', 'style', 'head', 'title'}


class _Converter(HTMLParser):
    """Basic HTML -> Markdown: paragraphs, line breaks, emphasis, lists, links, headings, quotes, code."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.lists, self.links, self.skip, self.quote, self.pre = [], [], [], 0, 0, 0

    def block(self):
        self.out.append('\n\n')

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag == 'br':
            self.out.append('  \n')
        elif tag in _BLOCKS:
            self.block()
            if tag == 'pre':
                self.pre += 1
                self.out.append('```\n')
            elif tag[0] == 'h' and tag[1:].isdigit():
                self.out.append('#' * min(int(tag[1:]) + 2, 6) + ' ')
        elif tag in ('strong', 'b'):
            self.out.append('**')
        elif tag in ('em', 'i'):
            self.out.append('*')
        elif tag == 'code' and not self.pre:
            self.out.append('`')
        elif tag in ('ul', 'ol'):
            self.block()
            self.lists.append([tag, 0])
        elif tag == 'li':
            depth = max(len(self.lists) - 1, 0)
            kind = self.lists[-1] if self.lists else ['ul', 0]
            kind[1] += 1
            self.out.append('\n' + '   ' * depth + (f'{kind[1]}. ' if kind[0] == 'ol' else '- '))
        elif tag == 'blockquote':
            self.block()
            self.quote += 1
        elif tag == 'a':
            self.links.append(dict(attrs).get('href') or '')
            self.out.append('[')
        elif tag in ('td', 'th'):
            self.out.append(' | ')

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(self.skip - 1, 0)
        elif tag in _BLOCKS:
            if tag == 'pre':
                self.out.append('\n```')
                self.pre = max(self.pre - 1, 0)
            self.block()
        elif tag in ('strong', 'b'):
            self.out.append('**')
        elif tag in ('em', 'i'):
            self.out.append('*')
        elif tag == 'code' and not self.pre:
            self.out.append('`')
        elif tag in ('ul', 'ol'):
            if self.lists:
                self.lists.pop()
            self.block()
        elif tag == 'blockquote':
            self.quote = max(self.quote - 1, 0)
            self.block()
        elif tag == 'a' and self.links:
            href = self.links.pop()
            self.out.append(f']({href})' if href.startswith(('http://', 'https://', 'mailto:')) else ']')

    def handle_data(self, data):
        if self.skip:
            return
        if not self.pre:
            data = re.sub(r'\s+', ' ', data)
        if self.quote:
            data = data.replace('\n', '\n> ')
            if not self.out or self.out[-1].endswith('\n'):
                data = '> ' + data.lstrip()
        self.out.append(data)


def html_to_markdown(html):
    if not html:
        return ''
    converter = _Converter()
    converter.feed(str(html))
    converter.close()
    text = ''.join(converter.out)
    text = re.sub(r'[ \t]+\n', lambda m: '  \n' if m.group().startswith('  ') else '\n', text)
    text = re.sub(r'\n[ \t]+(?=[^ \t\-\d])', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def pseudonyms(salt, user_ids):
    """Stable 'Student NN' labels for a workspace. Ordered by a salted hash so labels do not reveal alphabetical order."""
    ordered = sorted(set(user_ids), key=lambda u: hashlib.sha256(f'{salt}:{u}'.encode()).hexdigest())
    width = max(2, len(str(len(ordered))))
    return {u: f'Student {n:0{width}d}' for n, u in enumerate(ordered, 1)}


def latest_attempts(records):
    """One record per student: their highest attempt."""
    latest = {}
    for r in records:
        if r['user_id'] not in latest or (r['attempt'], r['submission_id']) > (latest[r['user_id']]['attempt'], latest[r['user_id']]['submission_id']):
            latest[r['user_id']] = r
    return list(latest.values())


def _answer(r):
    if not r.get('available', True):
        return '*Answer unavailable from Canvas.*'
    if r['answer'] is None:
        return '*Unanswered.*'
    return html_to_markdown(r['answer']) or '*Blank answer submitted.*'


def question_markdown(title, question, records, labels, names=False):
    """Markdown for one question: prompt at the top, then each student's latest response."""
    records = latest_attempts(records)
    label = (lambda r: r['name']) if names else (lambda r: labels[r['user_id']])
    records.sort(key=lambda r: label(r).casefold())
    lines = [f'# {title}', '', f'## {question.get("question_name") or "Question"}', '']
    prompt = html_to_markdown(question.get('question_text'))
    if prompt:
        lines += ['**Prompt:**', '', prompt, '']
    lines += [f'*{question.get("points_possible")} points possible · {len(records)} students · latest attempt only · '
              f'{"names included" if names else "anonymized"} · exported {date.today().isoformat()}*', '', '---', '']
    for r in records:
        lines += [f'### {label(r)}', '', _answer(r), '', '---', '']
    return '\n'.join(lines).rstrip('-\n') + '\n'


def key_markdown(title, labels, names):
    """Private lookup table from pseudonym to student name. Keep it local."""
    rows = sorted((labels[u], names[u]) for u in labels)
    lines = [f'# Name key: {title}', '', '*Private. Do not share or upload this file.*', '', '| Label | Student |', '| --- | --- |']
    lines += [f'| {l} | {n.replace("|", "/")} |' for l, n in rows]
    return '\n'.join(lines) + '\n'


def filename(*parts):
    slug = re.sub(r'[^A-Za-z0-9]+', '-', ' '.join(str(p) for p in parts if p)).strip('-').lower()
    return (slug[:80].rstrip('-') or 'export') + '.md'
