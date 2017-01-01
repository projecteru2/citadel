# coding: utf-8
from urlparse import urlparse

import mapi
from etcd import Client
from flask_mako import MakoTemplates
from flask_oauthlib.client import OAuth
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from gitlab import Gitlab
from redis import Redis

from citadel.config import (HUB_ADDRESS, REDIS_URL, ETCD_URL, OAUTH2_BASE_URL,
                            OAUTH2_CLIENT_ID, OAUTH2_CLIENT_SECRET,
                            OAUTH2_ACCESS_TOKEN_URL, OAUTH2_AUTHORIZE_URL,
                            GITLAB_URL, GITLAB_PRIVATE_TOKEN)


def get_etcd_client(url):
    r = urlparse(url)
    return Client(r.hostname, r.port)


db = SQLAlchemy()
mako = MakoTemplates()
oauth = OAuth()
rds = Redis.from_url(REDIS_URL)
etcd = get_etcd_client(ETCD_URL)

sso = oauth.remote_app(
    'sso',
    consumer_key=OAUTH2_CLIENT_ID,
    consumer_secret=OAUTH2_CLIENT_SECRET,
    request_token_params={'scope': 'email'},
    base_url=OAUTH2_BASE_URL,
    request_token_url=None,
    access_token_url=OAUTH2_ACCESS_TOKEN_URL,
    authorize_url=OAUTH2_AUTHORIZE_URL,
)

gitlab = Gitlab(GITLAB_URL, private_token=GITLAB_PRIVATE_TOKEN)
sess = Session()
hub = mapi.MapiClient(HUB_ADDRESS)
