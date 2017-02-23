# -*- coding: utf-8 -*-
import itertools
import json
from datetime import timedelta, datetime
from time import sleep

from etcd import EtcdKeyNotFound
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import ObjectDeletedError

from citadel.config import UPGRADE_CONTAINER_IGNORE_ENV
from citadel.ext import db, get_etcd
from citadel.libs.datastructure import purge_none_val_from_dict
from citadel.libs.mimiron import set_mimiron_route, del_mimiron_route
from citadel.libs.utils import logger
from citadel.models.base import BaseModelMixin, PropsMixin, PropsItem
from citadel.publisher import Publisher
from citadel.rpc import get_core


class ContainerOverrideStatus(object):
    NONE = 0
    DEBUG = 1
    REMOVING = 2


class Container(BaseModelMixin, PropsMixin):
    __tablename__ = 'container'
    __table_args__ = (
        db.Index('appname_sha', 'appname', 'sha'),
    )

    appname = db.Column(db.CHAR(64), nullable=False)
    sha = db.Column(db.CHAR(64), nullable=False)
    container_id = db.Column(db.CHAR(64), nullable=False, index=True)
    entrypoint = db.Column(db.String(50), nullable=False)
    env = db.Column(db.String(50), nullable=False)
    cpu_quota = db.Column(db.Numeric(12, 3), nullable=False, default=1)
    zone = db.Column(db.String(50), nullable=False)
    podname = db.Column(db.String(50), nullable=False)
    nodename = db.Column(db.String(50), nullable=False)
    override_status = db.Column(db.Integer, default=ContainerOverrideStatus.NONE, nullable=False)

    initialized = PropsItem('initialized', default=0, type=int)

    def __str__(self):
        return 'Container(container_id=%s)' % self.container_id

    def get_uuid(self):
        return 'citadel:container:%s' % self.container_id

    @classmethod
    def create(cls, appname, sha, container_id, entrypoint, env, cpu_quota, zone, podname, nodename, override_status=ContainerOverrideStatus.NONE):
        try:
            c = cls(appname=appname, sha=sha, container_id=container_id,
                    entrypoint=entrypoint, env=env, cpu_quota=cpu_quota,
                    zone=zone, podname=podname, nodename=nodename,
                    override_status=override_status)
            db.session.add(c)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return None

        specs = c.release and c.release.specs
        if specs:
            set_mimiron_route(c.container_id, c.get_node(), specs.permitted_users)

        return c

    @classmethod
    def get_by_container_id(cls, container_id):
        """get by container_id, prefix can be used in container_id"""
        c = cls.query.filter(cls.container_id.like('{}%'.format(container_id))).first()
        if not c:
            return
        return c.inspect()

    @property
    def app(self):
        from .app import App
        return App.get_by_name(self.appname)

    @property
    def release(self):
        from .app import Release
        return Release.get_by_app_and_sha(self.appname, self.sha)

    @classmethod
    def get_by(cls, **kwargs):
        sha = kwargs.pop('sha', None)
        entrypoint = kwargs.pop('entrypoint', None)
        if entrypoint == '_all':
            # all means including all entrypoints
            entrypoint = None

        query_set = cls.query.filter_by(**purge_none_val_from_dict(kwargs))
        if entrypoint:
            query_set = query_set.filter(cls.entrypoint == entrypoint)

        if sha:
            query_set = query_set.filter(cls.sha.like('{}%'.format(sha)))

        res = query_set.order_by(cls.id.desc())
        return [c.inspect() for c in res]

    @classmethod
    def get(cls, id):
        c = super(Container, cls).get(id)
        return c.inspect()

    @classmethod
    def get_all(cls, start=0, limit=20):
        cs = super(Container, cls).get_all(start, limit)
        return [c.inspect() for c in cs]

    @property
    def networks(self):
        return self.info.get('NetworkSettings', {}).get('Networks', {})

    @property
    def deploy_options(self):
        release = self.release
        deploy_options = {
            'specs': release.specs_text,
            'appname': self.appname,
            'image': release.image,
            'zone': self.zone,
            'podname': self.podname,
            'nodename': self.nodename,
            'entrypoint': self.entrypoint,
            'cpu_quota': float(self.cpu_quota),
            'count': 1,
            'memory': self.info['HostConfig']['Memory'],
            'networks': {network_name: '' for network_name in self.networks},
            'env': [e for e in self.info['Config']['Env'] if not e.split('=', 1)[0] in UPGRADE_CONTAINER_IGNORE_ENV],
            'raw': release.raw,
        }
        return deploy_options

    @property
    def ident(self):
        return self.name.rsplit('_', 2)[-1]

    @property
    def healthy(self):
        # TODO: hard code, ugly
        agent2_container_path = '/agent2/{}.ricebook.link/containers/{}'.format(self.nodename, self.container_id)
        try:
            etcd = get_etcd(self.zone)
            res = etcd.read(agent2_container_path)
        except EtcdKeyNotFound:
            return False
        container_info = json.loads(res.value)
        # if missing 'Healthy', considered healthy
        return container_info.get('Healthy', True)

    @property
    def used_mem(self):
        mem = self.info.get('HostConfig', {}).get('Memory', 0)
        return mem

    @property
    def short_id(self):
        return self.container_id[:7]

    @property
    def short_sha(self):
        return self.sha[:7]

    def is_removing(self):
        return self.override_status == ContainerOverrideStatus.REMOVING

    def is_cronjob(self):
        return self.entrypoint in self.app.cronjob_entrypoints

    def is_debug(self):
        return self.override_status == ContainerOverrideStatus.DEBUG

    def mark_debug(self):
        self.override_status = ContainerOverrideStatus.DEBUG
        db.session.commit()

    def mark_removing(self):
        Publisher.remove_container(self)
        self.override_status = ContainerOverrideStatus.REMOVING
        db.session.commit()

    def mark_initialized(self):
        self.initialized = 1

    def wait_for_erection(self, timeout=timedelta(minutes=5), period=timedelta(seconds=5)):
        """wait until this container is healthy, timeout can be timedelta or
        seconds, if timeout is 0, don't even wait and just report healthy"""
        if not timeout:
            return True
        if not isinstance(timeout, timedelta):
            timeout = timedelta(seconds=timeout)

        if not isinstance(period, timedelta):
            period = timedelta(seconds=period)

        must_end = datetime.now() + timeout
        while datetime.now() < must_end:
            if self.healthy:
                return True
            sleep(period.seconds)

        return False

    def inspect(self):
        """must be called after get / create"""
        # 太尼玛假了...
        # docker inspect在删除容器的时候可能需要比较长的时间才有响应
        # 也可能响应过后就直接报错了
        # 所以不如正在删除的容器就不要去inspect了
        if self.override_status == ContainerOverrideStatus.REMOVING:
            self.name = 'unknown'
            self.info = {'State': {'Status': 'removing'}}
            return self

        c = get_core(self.zone).get_container(self.container_id)
        if not c:
            self.name = 'unknown'
            self.info = {}
            return self
        self.name = c.name
        self.info = json.loads(c.info)
        return self

    def status(self):
        # docker 删除容器的时候无法 inspect，所以不会展示出 InRemoval 这个状态
        if self.is_removing():
            return 'removing'
        if self.is_debug():
            return 'debug'
        status = self.info.get('State', {}).get('Status', 'unknown')
        if status == 'running' and not self.healthy:
            return 'sick'
        return status

    def get_ips(self):
        ips = []
        for name, network in self.networks.iteritems():
            # 如果是host模式要去取下node的IP
            if name == 'host':
                node = get_core(self.zone).get_node(self.podname, self.nodename)
                if not node:
                    continue
                ips.append(node.ip)
            # 其他的不管是bridge还是自定义的都可以直接取
            else:
                ips.append(network.get('IPAddress', ''))

        return [ip for ip in ips if ip]

    def get_backends(self):
        from .app import Release
        ips = self.get_ips()
        release = Release.get_by_app_and_sha(self.appname, self.sha)
        if not release:
            return []

        specs = release.specs
        entrypoint = specs.entrypoints[self.entrypoint]
        ports = entrypoint.ports
        if not ports:
            return []

        ports = [p.port for p in ports]
        return ['%s:%s' % (ip, port) for ip, port in itertools.product(ips, ports)]

    def get_node(self):
        return get_core(self.zone).get_node(self.podname, self.nodename)

    def delete(self):
        try:
            del_mimiron_route(self.container_id)
            self.destroy_props()
        except ObjectDeletedError:
            logger.warn('Error during deleting: Object %s already deleted', self)
            return None
        return super(Container, self).delete()

    def to_dict(self):
        d = super(Container, self).to_dict()
        d.update({
            'appname': self.appname,
            'sha': self.sha,
            'container_id': self.container_id,
            'entrypoint': self.entrypoint,
            'env': self.env,
            'cpu_quota': self.cpu_quota,
            'zone': self.zone,
            'podname': self.podname,
            'nodename': self.nodename,
            'name': self.name,
            'info': self.info,
            'backends': self.get_backends(),
            'ips': self.get_ips(),
        })
        return d
