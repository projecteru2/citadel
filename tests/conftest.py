# -*- coding: utf-8 -*-
import pytest
from six.moves.urllib_parse import urlparse

from .prepare import default_appname, default_git, default_sha, make_specs_text
from citadel.app import create_app
from citadel.ext import db, rds
from citadel.models import App, Release


@pytest.fixture
def app(request):
    app = create_app()
    app.config['TESTING'] = True

    ctx = app.app_context()
    ctx.push()

    def tear_down():
        ctx.pop()

    request.addfinalizer(tear_down)
    return app


@pytest.yield_fixture
def client(app):
    with app.test_client() as client:
        yield client


@pytest.fixture
def test_db(request, app):

    def check_service_host(uri):
        """只能在本地或者容器里跑测试"""
        u = urlparse(uri)
        return u.hostname in ('localhost', '127.0.0.1') or 'hub.ricebook.net__ci__' in u.hostname

    if not (check_service_host(app.config['SQLALCHEMY_DATABASE_URI']) and check_service_host(app.config['REDIS_URL'])):
        raise Exception('Need to run test on localhost or in container')

    db.create_all()
    app = App.get_or_create(default_appname, git=default_git)
    Release.create(app, default_sha, make_specs_text())

    def teardown():
        db.session.remove()
        db.drop_all()
        rds.flushdb()

    request.addfinalizer(teardown)
