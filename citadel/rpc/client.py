# -*- coding: utf-8 -*-

import grpc
import wrapt
from grpc import RpcError, StatusCode
from grpc.framework.interfaces.face import face
from more_itertools import peekable
from operator import attrgetter

from citadel.config import ZONE_CONFIG
from citadel.libs.cache import cache, clean_cache, ONE_DAY
from citadel.libs.exceptions import ActionError
from citadel.libs.utils import memoize, logger
from citadel.rpc import core_pb2 as pb
from citadel.rpc.core_pb2 import Empty, NodeAvailable, AddPodOptions, GetPodOptions, ListNodesOptions, GetNodeOptions, AddNodeOptions, RemoveNodeOptions, ContainerID, ContainerIDs, BackupOptions
from citadel.rpc.core_pb2_grpc import CoreRPCStub


def handle_grpc_exception(default=None):
    @wrapt.decorator
    def wrapper(wrapped, instance, args, kwargs):
        try:
            return wrapped(*args, **kwargs)
        except RpcError as e:
            if e.code() is StatusCode.UNAVAILABLE:
                raise
            logger.exception(e)

        return default() if callable(default) else default
    return wrapper


_STREAM_TIMEOUT = 3600
_UNARY_TIMEOUT = 5

_GET_NODE = 'citadel:getnode:{podname}:{nodename}'


class CoreRPC:

    def __init__(self, grpc_address):
        self.grpc_address = grpc_address

    def _get_stub(self):
        channel = grpc.insecure_channel(self.grpc_address)
        return CoreRPCStub(channel)

    @staticmethod
    def _peek_grpc(call):
        """peek一下stream的返回, 不next一次他是不会raise exception的"""
        try:
            ms = peekable(call)
            ms.peek()
        except (face.RemoteError, face.RemoteShutdownError) as e:
            raise ActionError(e.details)
        except face.AbortionError as e:
            raise ActionError('gRPC remote server not available')
        return ms

    @handle_grpc_exception(default=list)
    def list_pods(self):
        stub = self._get_stub()
        r = stub.ListPods(Empty(), _UNARY_TIMEOUT)
        return list(r.pods)

    @handle_grpc_exception(default=None)
    def create_pod(self, name, desc):
        stub = self._get_stub()
        opts = AddPodOptions(name=name, desc=desc)
        p = stub.AddPod(opts, _UNARY_TIMEOUT)
        return p

    @handle_grpc_exception(default=None)
    def get_pod(self, name):
        stub = self._get_stub()
        opts = GetPodOptions(name=name)
        p = stub.GetPod(opts, _UNARY_TIMEOUT)
        return p

    @handle_grpc_exception(default=list)
    def get_pod_nodes(self, name):
        stub = self._get_stub()
        opts = ListNodesOptions(podname=name, all=True)
        r = stub.ListPodNodes(opts, _UNARY_TIMEOUT)
        return sorted(list(r.nodes), key=attrgetter('name'))

    @handle_grpc_exception(default=list)
    def list_networks(self, podname, driver=None):
        stub = self._get_stub()
        opts = pb.ListNetworkOptions(podname=podname, driver=driver)
        r = stub.ListNetworks(opts, _UNARY_TIMEOUT)
        return list(r.networks)

    @handle_grpc_exception(default=None)
    @cache(_GET_NODE, ttl=ONE_DAY)
    def get_node(self, podname, nodename):
        stub = self._get_stub()
        opts = GetNodeOptions(podname=podname, nodename=nodename)
        n = stub.GetNode(opts, _UNARY_TIMEOUT)
        return n

    @handle_grpc_exception(default=None)
    def set_node_availability(self, podname, nodename, is_available=True):
        stub = self._get_stub()
        logger.debug('Set node %s:%s available: %s', podname, nodename, is_available)
        opts = NodeAvailable(podname=podname, nodename=nodename, available=is_available)
        n = stub.SetNodeAvailable(opts, _UNARY_TIMEOUT)
        return n

    @handle_grpc_exception(default=None)
    def add_node(self, nodename, endpoint, podname, cafile, certfile, keyfile, public):
        stub = self._get_stub()
        opts = AddNodeOptions(nodename=nodename,
                              endpoint=endpoint,
                              podname=podname,
                              cafile=cafile,
                              certfile=certfile,
                              keyfile=keyfile,
                              public=public)

        n = stub.AddNode(opts, _UNARY_TIMEOUT)

        clean_cache(_GET_NODE.format(podname=podname, nodename=nodename))
        return n

    @handle_grpc_exception(default=None)
    def remove_node(self, nodename, podname):
        stub = self._get_stub()
        opts = RemoveNodeOptions(nodename=nodename, podname=podname)

        p = stub.RemoveNode(opts, _UNARY_TIMEOUT)

        clean_cache(_GET_NODE.format(podname=podname, nodename=nodename))
        return p

    def build_image(self, opts):
        """
        BuildImageOptions is so complicated man, had to assemble else where
        """
        stub = self._get_stub()
        grpc_call = self._peek_grpc(stub.BuildImage(opts, _STREAM_TIMEOUT))
        for m in grpc_call:
            yield m

    def create_container(self, deploy_opt):
        stub = self._get_stub()
        grpc_call = self._peek_grpc(stub.CreateContainer(deploy_opt, _STREAM_TIMEOUT))
        for m in grpc_call:
            yield m

    def remove_container(self, ids, force=False):
        if isinstance(ids, str):
            ids = [ids]

        stub = self._get_stub()
        opts = pb.RemoveContainerOptions(ids=ids, force=force)
        grpc_call = self._peek_grpc(stub.RemoveContainer(opts, _STREAM_TIMEOUT))
        for m in grpc_call:
            yield m

    def backup(self, id_, src_path):
        stub = self._get_stub()
        opts = BackupOptions(id=id_, src_path=src_path)
        msg = stub.Backup(opts, _STREAM_TIMEOUT)
        return msg

    @handle_grpc_exception(default=list)
    def get_containers(self, ids):
        stub = self._get_stub()
        ids = ContainerIDs(ids=[ContainerID(id=i) for i in ids])

        cs = stub.GetContainers(ids, _UNARY_TIMEOUT)
        return [c for c in cs.containers]

    @handle_grpc_exception(default=None)
    def get_container(self, id):
        stub = self._get_stub()
        id = ContainerID(id=id)
        return stub.GetContainer(id, _UNARY_TIMEOUT)


@memoize
def get_core(zone):
    grpc_url = ZONE_CONFIG[zone]['CORE_URL']
    return CoreRPC(grpc_url)
