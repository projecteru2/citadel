import pytest
import requests
from humanfriendly import parse_size
from telnetlib import Telnet
from time import sleep

from .test_specs import make_specs, default_appname, default_sha, default_port, artifact_filename, artifact_content
from citadel.config import ZONE_CONFIG, BUILD_ZONE
from citadel.rpc import core_pb2 as pb
from citadel.rpc.client import get_core


core_online = False
try:
    for zone in ZONE_CONFIG.values():
        ip, port = zone['CORE_URL'].split(':')
        Telnet(ip, port).close()
        core_online = True
except ConnectionRefusedError:
    core_online = False

pytestmark = pytest.mark.skipif(not core_online, reason='one or more eru-core is offline, skip core-related tests')


# test core config
default_network_name = 'etest'
default_podname = 'eru'
default_cpu_quota = 0.2
default_memory = parse_size('256MB', binary=True)


def test_workflow():
    '''
    build, create, remove
    '''
    specs = make_specs()
    appname = default_appname
    builds_map = {stage_name: pb.Build(**build) for stage_name, build in specs.builds.items()}
    core_builds = pb.Builds(stages=specs.stages, builds=builds_map)
    opts = pb.BuildImageOptions(name=appname,
                                user=appname,
                                uid=12345,
                                tag=default_sha,
                                builds=core_builds)
    core = get_core(BUILD_ZONE)
    build_image_messages = list(core.build_image(opts))
    image = ''
    for m in build_image_messages:
        assert not m.error

    image = m.progress
    assert '{}:{}'.format(default_appname, default_sha) in image

    # now create container
    entrypoint_opt = pb.EntrypointOptions(name='web',
                                          command='python -m http.server',
                                          dir='/home/{}'.format(default_appname))
    networks = {default_network_name: ''}
    deploy_options = pb.DeployOptions(name=default_appname,
                                      entrypoint=entrypoint_opt,
                                      podname=default_podname,
                                      image=image,
                                      cpu_quota=default_cpu_quota,
                                      memory=default_memory,
                                      count=1,
                                      networks=networks)
    deploy_messages = list(core.create_container(deploy_options))
    assert len(deploy_messages) == 1
    deploy_message = deploy_messages[0]
    assert not deploy_message.error
    assert deploy_message.memory == default_memory
    assert deploy_message.podname == default_podname
    network = deploy_message.publish
    assert len(network) == 1
    network_name, ip = network.popitem()
    assert network_name == default_network_name
    # TODO: use health check functionality rather than sleep
    sleep(3)
    # checking if volume is correct
    artifact_url = 'http://{}:{}/{}'.format(ip, default_port[0], artifact_filename)
    artifact_response = requests.get(artifact_url)
    assert artifact_content in artifact_response.text

    # clean this up
    remove_container_messages = list(core.remove_container([deploy_message.id]))
    assert len(remove_container_messages) == 1
    remove_container_message = remove_container_messages[0]
    assert remove_container_message.success is True