from types import SimpleNamespace as Obj
from unittest.mock import MagicMock, patch
import hashlib
import pytest
from django.test import override_settings

from apps.monitoring.services.airos_soft_apply import apply_frequency, SOFT_APPLY, checked_exec
from apps.monitoring.services.ubiquiti_ssh import set_frequency, read_current_frequency, _connect

BOOT = '12345678-1234-1234-1234-123456789012'
OTHER_BOOT = '87654321-1234-1234-1234-123456789012'
PLAN = '#!/bin/sh\nreload_services'


@pytest.fixture(autouse=True)
def approved_test_plan(settings):
    settings.FREQUENCY_FAST_APPLY_PLAN_HASHES = {'': [hashlib.sha256(PLAN.encode()).hexdigest()]}


def command_fixture(*, reboot=False, wrong_freq=False, script=None, width=20, write_fails=False, disconnect=False, fast=True):
    commands = []
    state = {'freq': 5180, 'applied': False}
    def command(client, cmd):
        commands.append(cmd)
        if cmd == 'iwconfig ath0':
            freq = 5180 if wrong_freq else state['freq']
            return f'ath0 Frequency:{freq / 1000:.3f} GHz'
        if cmd == 'cat /proc/sys/kernel/random/boot_id':
            return OTHER_BOOT if reboot and state['applied'] else BOOT
        if cmd.startswith("grep -E '^radio\\.1\\.(freq|chanbw)="):
            return f'radio.1.freq=5180\nradio.1.chanbw={width}'
        if cmd in ('cat /tmp/system.cfg', 'cat /tmp/running.cfg'):
            return 'radio.1.freq=5180\nradio.1.chanbw=20'
        if cmd == 'cat /tmp/diff.sh' or cmd.startswith('cat /tmp/fai-freq-'):
            return script if script is not None else PLAN
        if cmd.startswith('if /sbin/ubntconf -p'):
            return 'FAST' if fast else 'REFUSED'
        if cmd.startswith('sed -i'):
            if write_fails:
                raise RuntimeError('écriture refusée')
            state['freq'] = 5200
        if cmd.startswith("grep -E '^radio\\.1\\.freq="):
            return f"radio.1.freq={state['freq']}"
        if cmd.startswith('/bin/sh /tmp/fai-freq-'):
            state['applied'] = True
            if disconnect:
                raise RuntimeError('SSH disconnected')
        return ''
    return commands, command


@pytest.mark.parametrize('disconnect', [False, True])
def test_soft_apply_verified_even_if_ssh_disconnects(disconnect):
    commands, command = command_fixture(disconnect=disconnect)
    clients = [MagicMock(), MagicMock()]
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(side_effect=clients), Obj(), 5200)
    assert result['ok']
    assert any(cmd.startswith('/bin/sh /tmp/fai-freq-') for cmd in commands)
    assert not any(cmd == 'reboot' or SOFT_APPLY in cmd for cmd in commands)
    for client in clients:
        client.close.assert_called()


def test_changed_boot_id_is_failure():
    commands, command = command_fixture(reboot=True)
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(side_effect=[MagicMock(), MagicMock()]), Obj(), 5200)
    assert not result['ok'] and result['reboot_detected']


def test_timeout_is_not_success():
    commands, command = command_fixture(wrong_freq=True)
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command), \
         patch('apps.monitoring.services.airos_soft_apply.time.monotonic', side_effect=[0, 1, 130]), \
         patch('apps.monitoring.services.airos_soft_apply.time.sleep'):
        result = apply_frequency(MagicMock(return_value=MagicMock()), Obj(), 5200)
    assert not result['ok'] and result['uncertain']


@pytest.mark.parametrize('script,width', [('reboot',20), ('shutdown -r now',20), ('',20), (None,40)])
def test_incompatible_device_is_blocked_before_writing(script, width):
    commands, command = command_fixture(script=script, width=width)
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(return_value=MagicMock()), Obj(), 5200)
    assert not result['ok'] and result['blocked']
    assert not any(cmd.startswith('/bin/sh ') or SOFT_APPLY in cmd for cmd in commands)


def test_failed_staging_restores_temporary_configuration():
    commands, command = command_fixture(write_fails=True)
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(return_value=MagicMock()), Obj(), 5200)
    assert not result['ok'] and result['blocked']
    assert any(cmd.startswith('cp /tmp/fai-freq-') and ' /tmp/system.cfg' in cmd for cmd in commands)
    assert f'{SOFT_APPLY} save' not in commands


def test_command_exit_code_is_checked():
    client = MagicMock()
    stdout, stderr = MagicMock(), MagicMock()
    stdout.read.return_value, stderr.read.return_value = b'', b'failed'
    stdout.channel.recv_exit_status.return_value = 1
    client.exec_command.return_value = (None, stdout, stderr)
    with pytest.raises(RuntimeError):
        checked_exec(client, 'test -x file')


@override_settings(ROUTER_CONTROL_DRY_RUN=False, FREQUENCY_COMMANDS_VERIFIED=True,
                   FREQUENCY_SOFT_APPLY_ALLOWED={'3': [5120, 5200]})
def test_whitelist_is_per_device_and_supports_validated_5120():
    with patch('apps.monitoring.services.airos_soft_apply.apply_frequency', return_value={'ok':True}) as apply:
        assert set_frequency(Obj(pk=3), 5120)['ok']
        assert set_frequency(Obj(pk=4), 5120)['blocked']
        assert set_frequency(Obj(pk=3), 5220)['blocked']
        assert apply.call_count == 1


def test_read_frequency_is_runtime_not_random_config_value():
    client = MagicMock()
    with patch('apps.monitoring.services.ubiquiti_ssh._connect', return_value=client), \
         patch('apps.monitoring.services.airos_soft_apply.checked_exec', return_value='ath0 Frequency:5.120 GHz'):
        assert read_current_frequency(Obj())['freq_mhz'] == 5120
    client.close.assert_called()


def test_connection_uses_existing_forwarding_and_antenna_username():
    client = MagicMock()
    device = Obj(management_host='10.0.0.6', ssh_port=22, username='wrong',
                 aireos_username='antenna-user', ssh_forward_port=2226,
                 parent_mikrotik=Obj(is_active=True, management_host='zt-router'))
    with patch('apps.monitoring.services.ubiquiti_ssh._build_client', return_value=client), \
         patch('apps.monitoring.services.ubiquiti_ssh._resolve_password', return_value='test-only'):
        _connect(device)
    args = client.connect.call_args.kwargs
    assert (args['hostname'], args['port'], args['username']) == ('zt-router', 2226, 'antenna-user')


def test_fast_refused_restores_config_without_fallback():
    commands, command = command_fixture(fast=False)
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(return_value=MagicMock()), Obj(), 5200)
    assert result['blocked'] and not result['ok']
    assert any(cmd.startswith('cp /tmp/fai-freq-') for cmd in commands)
    assert not any(cmd.startswith('/bin/sh ') or SOFT_APPLY in cmd for cmd in commands)


def test_unknown_fast_plan_never_executes(settings):
    settings.FREQUENCY_FAST_APPLY_PLAN_HASHES = {}
    commands, command = command_fixture()
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(return_value=MagicMock()), Obj(), 5200)
    assert result['blocked']
    assert not any(cmd.startswith('/bin/sh ') for cmd in commands)


@pytest.mark.parametrize('signal_command', [
    'kill -1 1', '/bin/kill -HUP 1', 'busybox kill -s HUP 1',
    'kill -TERM "$pid"', 'reboot', 'shutdown -r now',
])
def test_dangerous_plan_is_blocked_even_when_hash_approved(settings, signal_command):
    plan = signal_command + '\n/bin/chsw 5200 5200'
    settings.FREQUENCY_FAST_APPLY_PLAN_HASHES = {'': [hashlib.sha256(plan.encode()).hexdigest()]}
    commands, command = command_fixture(script=plan)
    with patch('apps.monitoring.services.airos_soft_apply.checked_exec', side_effect=command):
        result = apply_frequency(MagicMock(return_value=MagicMock()), Obj(), 5200)
    assert result['blocked'] and not result['ok']
    assert 'interdit' in result['message']
    assert not any(cmd.startswith('/bin/sh ') or cmd.startswith('/sbin/cfgmtd ') for cmd in commands)
    assert any(cmd.startswith('cp /tmp/fai-freq-') and ' /tmp/system.cfg' in cmd for cmd in commands)
