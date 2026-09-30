"""Request helpers shared by every grading mode's routes."""
import os
from flask import current_app, session, url_for
from canvas_api import CanvasClient
from publishing import Publisher

# Grading mode -> (page endpoint for a workspace, publisher class).
MODES = {'quiz': ('quiz.grade', Publisher)}


def storage():
    return current_app.extensions['storage']


def safe_mode():
    return os.getenv('CANVAS_SAFE_MODE', '').lower() in ('1', 'true', 'yes') or session.get('safe', False)


def canvas_client():
    return CanvasClient(os.getenv('CANVAS_BASE_URL', ''), os.getenv('CANVAS_TOKEN', ''))


def publisher(kind):
    factory = current_app.config.get('CANVAS_CLIENT_FACTORY')
    return MODES[kind or 'quiz'][1](storage(), factory() if factory else canvas_client())


def workspace_url(key):
    return url_for(MODES[storage().snapshot_kind(key)][0], key=key)
