from types import SimpleNamespace as Obj
from unittest.mock import MagicMock, patch
import pytest
from apps.monitoring.services.frequency_metrics import parse_radio, fetch_frequency_metrics

RADIO = 'Frequency:5.135 GHz Signal level=-77 dBm Noise level=-92 dBm'


def test_radio_measures_from_received_format():
    assert parse_radio(RADIO) == (5135, -77, -92)


@pytest.mark.parametrize('text', ['Frequency:5.135 GHz', '', 'Signal level=-77 dBm Noise level=-92 dBm'])
def test_missing_rf_is_not_invented(text):
    with pytest.raises(ValueError):
        parse_radio(text)


def test_forwarded_ssh_does_not_use_snmp():
    client = MagicMock()
    with patch('apps.monitoring.services.frequency_metrics._connect', return_value=client), \
         patch('apps.monitoring.services.frequency_metrics.checked_exec', side_effect=[RADIO, '[{"mac":"AA:BB:CC:DD:EE:FF"}]']), \
         patch('apps.monitoring.services.frequency_metrics.UbiquitiAirMAXSnmpService') as snmp:
        result = fetch_frequency_metrics(Obj(ssh_forward_port=2227))
    assert result.online and not result.error and result.client_count == 1
    assert result.rssi_dbm - result.noise_floor_dbm == 15
    snmp.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize('clients', ['bad json', '{}', '[{}]'])
def test_bad_client_list_blocks_metrics(clients):
    client = MagicMock()
    with patch('apps.monitoring.services.frequency_metrics._connect', return_value=client), \
         patch('apps.monitoring.services.frequency_metrics.checked_exec', side_effect=[RADIO, clients]):
        result = fetch_frequency_metrics(Obj(ssh_forward_port=2227))
    assert not result.online and result.error and result.client_count is None
    client.close.assert_called_once()


def test_devices_without_forwarding_keep_snmp():
    with patch('apps.monitoring.services.frequency_metrics.UbiquitiAirMAXSnmpService') as snmp, \
         patch('apps.monitoring.services.frequency_metrics._connect') as connect:
        fetch_frequency_metrics(Obj(ssh_forward_port=None))
        snmp.return_value.fetch_full_metrics.assert_called_once()
        connect.assert_not_called()
