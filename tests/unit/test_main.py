"""Test Main methods."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

from httpx import Response
from kytos.core.events import KytosEvent
from kytos.core.exceptions import (KytosTagsNotInTagRanges,
                                   KytosTagsAreNotAvailable)
from kytos.lib.helpers import (get_controller_mock, get_interface_mock,
                               get_kytos_event_mock, get_switch_mock,
                               get_test_client)
from napps.kytos.of_lldp.utils import get_cookie
from tenacity import RetryError

from tests.helpers import get_topology_mock


@patch('kytos.core.controller.Controller.get_switch_by_dpid')
@patch('napps.kytos.of_lldp.main.Main._unpack_non_empty')
@patch('napps.kytos.of_lldp.main.UBInt32')
@patch('napps.kytos.of_lldp.main.DPID')
@patch('napps.kytos.of_lldp.main.LLDP')
@patch('napps.kytos.of_lldp.main.Ethernet')
async def test_on_ofpt_packet_in(*args):
    """Test on_ofpt_packet_in."""
    (mock_ethernet, mock_lldp, mock_dpid, mock_ubint32,
     mock_unpack_non_empty, mock_get_switch_by_dpid) = args

    # pylint: disable=bad-option-value, import-outside-toplevel
    from napps.kytos.of_lldp.main import Main
    Main.get_liveness_controller = MagicMock()
    topology = get_topology_mock()
    controller = get_controller_mock()
    controller.buffers.app.aput = AsyncMock()
    controller.switches = topology.switches
    napp = Main(controller)
    napp.loop_manager.process_if_looped = AsyncMock()
    napp.liveness_manager.consume_hello_if_enabled = AsyncMock()

    switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
    message = MagicMock(in_port=1, data='data')
    event = KytosEvent('ofpt_packet_in', content={'source': switch.connection,
                       'message': message})

    mocked, ethernet, lldp, dpid, port_b = [MagicMock() for _ in range(5)]
    mocked.value = 1
    mock_ubint32.return_value = mocked
    ethernet.ether_type = 0x88CC
    ethernet.data = 'eth_data'
    lldp.chassis_id.sub_value = 'chassis_id'
    lldp.port_id.sub_value = 'port_id'
    dpid.value = "00:00:00:00:00:00:00:02"
    port_b.value = 2

    mock_unpack_non_empty.side_effect = [ethernet, lldp, dpid, port_b]
    mock_get_switch_by_dpid.return_value = get_switch_mock(dpid.value,
                                                           0x04)
    await napp.on_ofpt_packet_in(event)

    calls = [call(mock_ethernet, message.data),
             call(mock_lldp, ethernet.data),
             call(mock_dpid, lldp.chassis_id.sub_value),
             call(mock_ubint32, lldp.port_id.sub_value)]
    mock_unpack_non_empty.assert_has_calls(calls)
    assert napp.loop_manager.process_if_looped.call_count == 1
    assert napp.liveness_manager.consume_hello_if_enabled.call_count == 1
    assert controller.buffers.app.aput.call_count == 1


@patch('kytos.core.controller.Controller.get_switch_by_dpid')
@patch('napps.kytos.of_lldp.main.Main._unpack_non_empty')
@patch('napps.kytos.of_lldp.main.UBInt32')
@patch('napps.kytos.of_lldp.main.DPID')
@patch('napps.kytos.of_lldp.main.LLDP')
@patch('napps.kytos.of_lldp.main.Ethernet')
async def test_on_ofpt_packet_in_early_intf(*args):
    """Test on_ofpt_packet_in early intf return."""
    (mock_ethernet, mock_lldp, mock_dpid, mock_ubint32,
     mock_unpack_non_empty, mock_get_switch_by_dpid) = args

    # pylint: disable=bad-option-value, import-outside-toplevel
    from napps.kytos.of_lldp.main import Main
    Main.get_liveness_controller = MagicMock()
    topology = get_topology_mock()
    controller = get_controller_mock()
    controller.buffers.app.aput = AsyncMock()
    controller.switches = topology.switches
    napp = Main(controller)
    napp.loop_manager.process_if_looped = AsyncMock()
    napp.liveness_manager.consume_hello_if_enabled = AsyncMock()

    switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
    message = MagicMock(in_port=1, data='data')
    event = KytosEvent('ofpt_packet_in', content={'source': switch.connection,
                       'message': message})

    mocked, ethernet, lldp, dpid, port_b = [MagicMock() for _ in range(5)]
    mocked.value = 1
    mock_ubint32.return_value = mocked
    ethernet.ether_type = 0x88CC
    ethernet.data = 'eth_data'
    lldp.chassis_id.sub_value = 'chassis_id'
    lldp.port_id.sub_value = 'port_id'
    dpid.value = "00:00:00:00:00:00:00:02"
    port_b.value = 2

    mock_unpack_non_empty.side_effect = [ethernet, lldp, dpid, port_b]
    mock_get_switch_by_dpid.return_value = get_switch_mock(dpid.value,
                                                           0x04)
    switch.get_interface_by_port_no = MagicMock(return_value=None)
    await napp.on_ofpt_packet_in(event)

    calls = [call(mock_ethernet, message.data),
             call(mock_lldp, ethernet.data),
             call(mock_dpid, lldp.chassis_id.sub_value),
             call(mock_ubint32, lldp.port_id.sub_value)]
    mock_unpack_non_empty.assert_has_calls(calls)
    switch.get_interface_by_port_no.assert_called()
    # early return shouldn't allow these to get called
    assert napp.loop_manager.process_if_looped.call_count == 0
    assert napp.liveness_manager.consume_hello_if_enabled.call_count == 0
    assert controller.buffers.app.aput.call_count == 0


async def test_on_table_enabled():
    """Test on_table_enabled"""
    # pylint: disable=bad-option-value, import-outside-toplevel
    from napps.kytos.of_lldp.main import Main
    controller = get_controller_mock()
    controller.buffers.app.aput = AsyncMock()
    napp = Main(controller)

    # Succesfully setting table groups
    content = {"of_lldp": {"base": 123}}
    event = KytosEvent(name="kytos/of_multi_table.enable_table",
                       content=content)
    await napp.on_table_enabled(event)
    assert napp.table_group == content["of_lldp"]
    assert controller.buffers.app.aput.call_count == 1

    # Failure at setting table groups
    content = {"of_lldp": {"unknown": 123}}
    event = KytosEvent(name="kytos/of_multi_table.enable_table",
                       content=content)
    await napp.on_table_enabled(event)
    assert controller.buffers.app.aput.call_count == 1


# pylint: disable=protected-access,too-many-public-methods
class TestMain:
    """Tests for the Main class."""

    def setup_method(self):
        """Execute steps before each tests."""
        # patch('kytos.core.helpers.run_on_thread', lambda x: x).start()
        # pylint: disable=bad-option-value, import-outside-toplevel
        from napps.kytos.of_lldp.main import Main
        Main.get_liveness_controller = MagicMock()
        self.topology = get_topology_mock()
        controller = get_controller_mock()
        controller.switches = self.topology.switches
        self.base_endpoint = "kytos/of_lldp/v1"
        self.napp = Main(controller)
        self.api_client = get_test_client(controller, self.napp)

    def teardown_method(self) -> None:
        """Teardown."""
        patch.stopall()

    def get_topology_interfaces(self):
        """Return interfaces present in topology."""
        interfaces = []
        for switch in list(self.topology.switches.values()):
            interfaces += list(switch.interfaces.values())
        return interfaces

    @patch('napps.kytos.of_lldp.main.of_msg_prio')
    @patch('napps.kytos.of_lldp.main.KytosEvent')
    @patch('napps.kytos.of_lldp.main.VLAN')
    @patch('napps.kytos.of_lldp.main.Ethernet')
    @patch('napps.kytos.of_lldp.main.DPID')
    @patch('napps.kytos.of_lldp.main.LLDP')
    def test_execute(self, *args):
        """Test execute method."""
        (_, _, mock_ethernet, _, mock_kytos_event, mock_of_msg_prio) = args
        mock_buffer_put = MagicMock()
        self.napp.controller.buffers.msg_out.put = mock_buffer_put

        ethernet = MagicMock()
        ethernet.pack.return_value = 'pack'
        interfaces = self.get_topology_interfaces()
        po_args = [(interface.switch.connection.protocol.version,
                    interface.port_number, 'pack') for interface in interfaces]

        mock_ethernet.return_value = ethernet
        mock_kytos_event.side_effect = po_args

        mock_publish_stopped = MagicMock()
        self.napp.try_to_publish_stopped_loops = mock_publish_stopped
        self.napp.execute()

        mock_of_msg_prio.assert_called()
        mock_buffer_put.assert_has_calls([call(arg)
                                          for arg in po_args])
        mock_publish_stopped.assert_called()

    @patch('napps.kytos.of_lldp.main.Main.get_flows_by_switch')
    def test_handle_lldp_flows(self, mock_flows, monkeypatch):
        """Test handle_lldp_flow method."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
        self.napp.controller.switches = {dpid: switch}
        event_post = get_kytos_event_mock(name='kytos/topology.switch.enabled',
                                          content={'dpid': dpid})

        event_del = get_kytos_event_mock(name='kytos/topology.switch.disabled',
                                         content={'dpid': dpid})

        mock_post, mock_del = MagicMock(), MagicMock()
        mock_post.return_value = Response(status_code=202)
        mock_del.return_value = Response(status_code=202)
        monkeypatch.setattr("httpx.post", mock_post)
        monkeypatch.setattr("httpx.request", mock_del)

        mock_flows.return_value = {}
        self.napp.use_vlan = MagicMock()
        self.napp._handle_lldp_flows(event_post)
        mock_post.assert_called()
        self.napp.use_vlan.assert_called_with(switch)

        mock_flows.return_value = {"flows": "mocked_flows"}
        self.napp.make_vlan_available = MagicMock()
        self.napp._handle_lldp_flows(event_del)
        mock_del.assert_called()
        self.napp.make_vlan_available.assert_called_with(switch)

    @patch('napps.kytos.of_lldp.main.Main.get_flows_by_switch')
    @patch("time.sleep")
    def test_handle_lldp_flows_retries(self, _, mock_flows, monkeypatch):
        """Test handle_lldp_flow method retries."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
        mock_flows.return_value = {}
        mock_post = MagicMock()
        monkeypatch.setattr("httpx.post", mock_post)
        self.napp.controller.switches = {dpid: switch}
        event_post = get_kytos_event_mock(name="kytos/topology.switch.enabled",
                                          content={"dpid": dpid})

        mock = MagicMock()
        mock.request.method = "POST"
        mock.status_code = 500
        mock.text = "some_err"
        mock_post.return_value = mock
        self.napp._handle_lldp_flows(event_post)
        assert mock_post.call_count == 3

    @patch('napps.kytos.of_lldp.main.log')
    def test_handle_lldp_flows_request_value_error(self, mock_log,
                                                   monkeypatch):
        """Test _handle_lldp_flows"""
        dpid = "00:00:00:00:00:00:00:01"
        mock_get = MagicMock()
        mock_get.return_value = MagicMock(
            status_code=400, is_server_error=False
        )
        event_post = get_kytos_event_mock(name='kytos/topology.switch.enabled',
                                          content={'dpid': dpid})
        monkeypatch.setattr("httpx.get", mock_get)
        self.napp._handle_lldp_flows(event_post)
        assert mock_log.error.call_count == 1

    @patch('napps.kytos.of_lldp.main.log')
    def test_handle_lldp_flows_request_error(self, mock_log):
        """Test _handle_lldp_flows"""
        dpid = "00:00:00:00:00:00:00:01"
        event_post = get_kytos_event_mock(name='kytos/topology.switch.enabled',
                                          content={'dpid': dpid})
        self.napp.get_flows_by_switch = MagicMock()
        exc = RetryError(MagicMock())
        self.napp.get_flows_by_switch.side_effect = exc
        self.napp._handle_lldp_flows(event_post)
        assert mock_log.error.call_count == 1

    @patch('napps.kytos.of_lldp.main.PO13')
    @patch('napps.kytos.of_lldp.main.AO13')
    def test_build_lldp_packet_out(self, *args):
        """Test _build_lldp_packet_out method."""
        (mock_ao13, mock_po13) = args

        ao13 = MagicMock()
        po13 = MagicMock()
        po13.actions = []

        mock_ao13.return_value = ao13
        mock_po13.return_value = po13

        packet_out13 = self.napp._build_lldp_packet_out(0x04, 2, 'data2')
        packet_out14 = self.napp._build_lldp_packet_out(0x05, 3, 'data3')

        assert packet_out13.data == 'data2'
        assert packet_out13.actions == [ao13]
        assert packet_out13.actions[0].port == 2
        assert packet_out14 is None

    @patch('napps.kytos.of_lldp.main.settings')
    @patch('napps.kytos.of_lldp.main.EtherType')
    @patch('napps.kytos.of_lldp.main.Port13')
    def test_build_lldp_flow(self, *args):
        """Test _build_lldp_flow method."""
        (mock_v0x04_port, mock_ethertype,
         mock_settings) = args
        self.napp.vlan_id = None
        mock_v0x04_port.OFPP_CONTROLLER = 1234

        mock_ethertype.LLDP = 10
        mock_settings.FLOW_VLAN_VID = None
        mock_settings.FLOW_PRIORITY = 1500
        dpid = "00:00:00:00:00:00:00:01"

        flow = {}
        match = {}
        flow['priority'] = 1500
        flow['table_id'] = 0
        match['dl_type'] = 10

        flow['match'] = match
        expected_flow_v0x04 = flow.copy()
        expected_flow_v0x04['cookie'] = get_cookie(dpid)
        expected_flow_v0x04['cookie_mask'] = 0xffffffffffffffff

        expected_flow_v0x04['actions'] = [{'action_type': 'output',
                                           'port': 1234}]
        expected_flow_v0x04['table_group'] = 'base'
        expected_flow_v0x04['owner'] = 'of_lldp'

        flow_mod10 = self.napp._build_lldp_flow(0x01, get_cookie(dpid))
        flow_mod13 = self.napp._build_lldp_flow(0x04, get_cookie(dpid))

        assert flow_mod10 is None
        assert flow_mod13 == expected_flow_v0x04

    def test_unpack_non_empty(self):
        """Test _unpack_non_empty method."""
        desired_class = MagicMock()
        data = MagicMock()
        data.value = 'data'

        obj = self.napp._unpack_non_empty(desired_class, data)

        obj.unpack.assert_called_with('data')

    def test_get_data(self, monkeypatch):
        """Test _get_data method."""
        interfaces = ['00:00:00:00:00:00:00:01:1', '00:00:00:00:00:00:00:01:2']
        monkeypatch.setattr("napps.kytos.of_lldp.main.get_json_or_400",
                            lambda req, loop: {"interfaces": interfaces})
        data = self.napp._get_data(MagicMock())
        assert data == interfaces

    def test_load_liveness(self) -> None:
        """Test load_liveness."""
        self.napp.load_liveness()
        count = self.napp.liveness_controller.get_enabled_interfaces.call_count
        assert count == 1
        assert not self.napp.liveness_manager.interfaces

    def test_load_liveness_enabled(self) -> None:
        """Test load_liveness enabled."""
        mocked = MagicMock()
        intf_id = "00:00:00:00:00:00:00:01:1"
        mocked.return_value = [{"id": intf_id}]
        self.napp.liveness_controller.get_enabled_interfaces = mocked
        self.napp.load_liveness()
        count = self.napp.liveness_controller.get_enabled_interfaces.call_count
        assert count == 1
        assert intf_id in self.napp.liveness_manager.interfaces

    async def test_on_topology_loaded(self) -> None:
        """Test on_topology_loaded."""
        event = KytosEvent("kytos/topology.topology_loaded",
                           content={"topology": {}})
        self.napp.load_liveness = MagicMock()
        self.napp.loop_manager.handle_topology_loaded = AsyncMock()
        await self.napp.on_topology_loaded(event)
        assert self.napp.loop_manager.handle_topology_loaded.call_count == 1
        assert self.napp.load_liveness.call_count == 1

    def test_publish_liveness_status(self) -> None:
        """Test publish_liveness_status."""
        self.napp.controller.buffers.app.put = MagicMock()
        event_suffix, interfaces = "up", [MagicMock(id=1), MagicMock(id=2)]
        self.napp.publish_liveness_status(event_suffix, interfaces)
        assert self.napp.controller.buffers.app.put.call_count == 1
        event = self.napp.controller.buffers.app.put.call_args[0][0]
        assert event.name == f"kytos/of_lldp.liveness.{event_suffix}"
        assert event.content["interfaces"] == interfaces

    def test_get_interfaces(self):
        """Test _get_interfaces method."""
        expected_interfaces = self.get_topology_interfaces()
        interfaces = self.napp._get_interfaces()
        assert interfaces == expected_interfaces

    def test_get_interfaces_dict(self):
        """Test _get_interfaces_dict method."""
        interfaces = self.napp._get_interfaces()
        expected_interfaces = {inter.id: inter for inter in interfaces}
        interfaces_dict = self.napp._get_interfaces_dict(interfaces)
        assert interfaces_dict == expected_interfaces

    def test_get_lldp_interfaces(self):
        """Test _get_lldp_interfaces method."""
        lldp_interfaces = self.napp._get_lldp_interfaces()
        expected_interfaces = ['00:00:00:00:00:00:00:01:1',
                               '00:00:00:00:00:00:00:01:2',
                               '00:00:00:00:00:00:00:02:1',
                               '00:00:00:00:00:00:00:02:2']
        assert lldp_interfaces == expected_interfaces

    async def test_rest_get_lldp_interfaces(self):
        """Test get_lldp_interfaces method."""
        endpoint = f"{self.base_endpoint}/interfaces"
        response = await self.api_client.get(endpoint)
        expected_data = {"interfaces": ['00:00:00:00:00:00:00:01:1',
                                        '00:00:00:00:00:00:00:01:2',
                                        '00:00:00:00:00:00:00:02:1',
                                        '00:00:00:00:00:00:00:02:2']}
        assert response.status_code == 200
        assert response.json() == expected_data

    async def test_enable_disable_lldp_200(self):
        """Test 200 response for enable_lldp and disable_lldp methods."""
        data = {"interfaces": ['00:00:00:00:00:00:00:01:1',
                               '00:00:00:00:00:00:00:01:2',
                               '00:00:00:00:00:00:00:02:1',
                               '00:00:00:00:00:00:00:02:2']}
        self.napp.controller.loop = asyncio.get_running_loop()
        self.napp.publish_liveness_status = MagicMock()
        endpoint = f"{self.base_endpoint}/interfaces/disable"
        response = await self.api_client.post(endpoint, json=data)
        assert response.status_code == 200
        assert self.napp.liveness_controller.disable_interfaces.call_count == 1
        assert self.napp.publish_liveness_status.call_count == 1
        endpoint = f"{self.base_endpoint}/interfaces/enable"
        response = await self.api_client.post(endpoint, json=data)
        assert response.status_code == 200

    async def test_enable_disable_lldp_404(self):
        """Test 404 response for enable_lldp and disable_lldp methods."""
        data = {"interfaces": []}
        self.napp.controller.switches = {}
        endpoint = f"{self.base_endpoint}/disable"
        response = await self.api_client.post(endpoint, json=data)
        assert response.status_code == 404
        endpoint = f"{self.base_endpoint}/enable"
        response = await self.api_client.post(endpoint, json=data)
        assert response.status_code == 404

    async def test_enable_disable_lldp_400(self):
        """Test 400 response for enable_lldp and disable_lldp methods."""
        data = {"interfaces": ['00:00:00:00:00:00:00:01:1',
                               '00:00:00:00:00:00:00:01:2',
                               '00:00:00:00:00:00:00:02:1',
                               '00:00:00:00:00:00:00:02:2',
                               '00:00:00:00:00:00:00:03:1',
                               '00:00:00:00:00:00:00:03:2',
                               '00:00:00:00:00:00:00:04:1']}
        self.napp.controller.loop = asyncio.get_running_loop()
        self.napp.publish_liveness_status = MagicMock()
        url = f'{self.base_endpoint}/interfaces/disable'
        response = await self.api_client.post(url, json=data)
        assert response.status_code == 400
        assert self.napp.publish_liveness_status.call_count == 1

        url = f'{self.base_endpoint}/interfaces/enable'
        response = await self.api_client.post(url, json=data)
        assert response.status_code == 400

    async def test_get_time(self):
        """Test get polling time."""
        url = f"{self.base_endpoint}/polling_time"
        response = await self.api_client.get(url)
        assert response.status_code == 200

    async def test_set_polling_time(self):
        """Test update polling time."""
        url = f"{self.base_endpoint}/polling_time"
        data = {'polling_time': 5}
        response = await self.api_client.post(url, json=data)
        assert response.status_code == 200

    async def test_set_time_400(self):
        """Test fail case the update polling time."""
        url = f"{self.base_endpoint}/polling_time"
        data = {'polling_time': 'A'}
        response = await self.api_client.post(url, json=data)
        assert response.status_code == 400

    async def test_endpoint_enable_liveness(self):
        """Test POST v1/liveness/enable."""
        self.napp.controller.loop = asyncio.get_running_loop()
        self.napp.liveness_manager.enable = MagicMock()
        self.napp.publish_liveness_status = MagicMock()
        url = f"{self.base_endpoint}/liveness/enable"
        data = {"interfaces": ["00:00:00:00:00:00:00:01:1"]}
        response = await self.api_client.post(url, json=data)
        assert response.status_code == 200
        assert response.json() == {}
        assert self.napp.liveness_controller.enable_interfaces.call_count == 1
        assert self.napp.liveness_manager.enable.call_count == 1
        assert self.napp.publish_liveness_status.call_count == 1

    async def test_endpoint_disable_liveness(self):
        """Test POST v1/liveness/disable."""
        self.napp.controller.loop = asyncio.get_running_loop()
        self.napp.liveness_manager.disable = MagicMock()
        self.napp.publish_liveness_status = MagicMock()
        url = f"{self.base_endpoint}/liveness/disable"
        data = {"interfaces": ["00:00:00:00:00:00:00:01:1"]}
        response = await self.api_client.post(url, json=data)
        assert response.status_code == 200
        assert response.json() == {}
        assert self.napp.liveness_controller.disable_interfaces.call_count == 1
        assert self.napp.liveness_manager.disable.call_count == 1
        assert self.napp.publish_liveness_status.call_count == 1

    async def test_endpoint_get_liveness(self):
        """Test GET v1/liveness/."""
        self.napp.liveness_manager.enable = MagicMock()
        self.napp.publish_liveness_status = MagicMock()
        url = f"{self.base_endpoint}/liveness/"
        response = await self.api_client.get(url)
        assert response.status_code == 200
        assert response.json() == {"interfaces": []}

    async def test_endpoint_get_pair_liveness(self):
        """Test GET v1/liveness//pair."""
        self.napp.liveness_manager.enable = MagicMock()
        self.napp.publish_liveness_status = MagicMock()
        url = f"{self.base_endpoint}/liveness/pair"
        response = await self.api_client.get(url)
        assert response.status_code == 200
        assert response.json() == {"pairs": []}

    def test_set_flow_table_group_owner(self):
        """Test set_flow_table_group_owner"""
        self.napp.table_group = {"base": 2}
        flow = {}
        self.napp.set_flow_table_group_owner(flow, "base")
        assert "table_group" in flow
        assert "owner" in flow
        assert flow["table_id"] == 2

    @patch('napps.kytos.of_lldp.main.log')
    def test_use_vlan(self, mock_log):
        """Test use_vlan"""
        switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
        interface_a = get_interface_mock("mock_a", 1, switch)
        interface_a.use_tags = MagicMock()
        interface_b = get_interface_mock("mock_b", 2, switch)
        interface_b.use_tags = MagicMock()
        switch.interfaces = {1: interface_a, 2: interface_b}
        self.napp.use_vlan(switch)
        assert interface_a.use_tags.call_count == 1
        assert interface_b.use_tags.call_count == 1

        interface_a.use_tags.side_effect = KytosTagsAreNotAvailable([], "1")
        self.napp.use_vlan(switch)
        assert interface_a.use_tags.call_count == 2
        assert interface_b.use_tags.call_count == 2
        assert mock_log.error.call_count == 1

        self.napp.vlan_id = None
        self.napp.use_vlan(switch)
        assert interface_a.use_tags.call_count == 2
        assert interface_b.use_tags.call_count == 2

    @patch('napps.kytos.of_lldp.main.log')
    def test_make_vlan_available(self, mock_log):
        """Test make_vlan_available"""
        switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
        interface_a = get_interface_mock("mock_a", 1, switch)
        interface_a.make_tags_available = MagicMock()
        a_make_ava = interface_a.make_tags_available
        a_make_ava.return_value = []
        interface_b = get_interface_mock("mock_b", 2, switch)
        interface_b.make_tags_available = MagicMock()
        b_make_ava = interface_b.make_tags_available
        b_make_ava.return_value = []
        switch.interfaces = {1: interface_a, 2: interface_b}
        self.napp.make_vlan_available(switch)
        assert interface_a.make_tags_available.call_count == 1
        assert interface_b.make_tags_available.call_count == 1

        a_make_ava.return_value = [[3799, 3799]]
        self.napp.make_vlan_available(switch)
        assert interface_a.make_tags_available.call_count == 2
        assert interface_b.make_tags_available.call_count == 2
        assert mock_log.warning.call_count == 1

        self.napp.vlan_id = None
        self.napp.make_vlan_available(switch)
        assert interface_a.make_tags_available.call_count == 2
        assert interface_b.make_tags_available.call_count == 2

        self.napp.vlan_id = 3799
        b_make_ava.side_effect = KytosTagsNotInTagRanges(
            [[3799, 3799]], "01:2"
        )
        self.napp.make_vlan_available(switch)
        assert interface_a.make_tags_available.call_count == 3
        assert interface_b.make_tags_available.call_count == 3
        assert mock_log.error.call_count == 1

    @patch('napps.kytos.of_lldp.main.Main.use_vlan')
    def test_send_flow_enabled(self, mock_use, monkeypatch):
        """Test send_flows when switch is enabled"""
        mock_post = MagicMock()
        monkeypatch.setattr("httpx.post", mock_post)
        mock_post.return_value = MagicMock(
            status_code=202, is_server_error=False
        )
        event_name = 'kytos/topology.switch.enabled'
        switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
        data = {'flows': [{'cookie_mask': "mock_cookie"}]}
        self.napp.send_flow(switch, event_name, data=data)

        assert mock_use.call_count == 1
        assert mock_use.call_args[0][0] == switch
        assert data['flows'] == [{}]

    @patch('napps.kytos.of_lldp.main.Main.make_vlan_available')
    def test_send_flow_disabled(self, mock_avaialble, monkeypatch):
        """Test send_flows when switch is disabled"""
        mock_request = MagicMock()
        monkeypatch.setattr("httpx.request", mock_request)
        mock_request.return_value = MagicMock(
            status_code=202, is_server_error=False
        )
        event_name = 'kytos/topology.switch.disabled'
        switch = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
        data = {'flows': [{'cookie_mask': "mock_cookie"}]}
        self.napp.send_flow(switch, event_name, data=data)

        assert mock_avaialble.call_count == 1
        assert mock_avaialble.call_args[0][0] == switch
        assert data['flows'] == [{'cookie_mask': "mock_cookie"}]

    def test_on_interface_deleted(self):
        """Test on interface deleted"""
        intf_id = "00:00:00:00:00:00:00:01:1"
        intf = MagicMock()
        intf.id = intf_id
        self.napp.liveness_manager.interfaces[intf_id] = intf
        content = {"interface": intf}
        event = KytosEvent(content=content)
        self.napp.on_interface_deleted(event)
        assert intf.id not in self.napp.liveness_manager.interfaces
        assert self.napp.liveness_controller.delete_interface.call_count == 1

    def test_on_interface_deleted_not_loaded(self):
        """Test on interface deleted not loaded"""
        intf_id = "00:00:00:00:00:00:00:01:1"
        intf = MagicMock()
        intf.id = intf_id
        self.napp.liveness_manager.interfaces["some_id"] = intf
        content = {"interface": intf}
        event = KytosEvent(content=content)
        self.napp.on_interface_deleted(event)
        assert "some_id" in self.napp.liveness_manager.interfaces
        assert intf.id not in self.napp.liveness_manager.interfaces
        assert not self.napp.liveness_controller.delete_interface.call_count

    def test_on_switch_deleted(self):
        """Test on switch deleted"""
        intf_id = "00:00:00:00:00:00:00:01"
        switch = MagicMock()
        intf = MagicMock()
        intf.id = intf_id
        switch.interfaces = {intf_id: intf}
        self.napp.liveness_manager.interfaces[intf_id] = intf
        content = {"switch": switch}
        event = KytosEvent(content=content)
        self.napp.on_switch_deleted(event)
        assert intf.id not in self.napp.liveness_manager.interfaces
        assert self.napp.liveness_controller.delete_interfaces.call_count == 1

    def test_on_switch_deleted_not_loaded(self):
        """Test on switch deleted not loaded"""
        intf_id = "00:00:00:00:00:00:00:01"
        switch = MagicMock()
        intf = MagicMock()
        intf.id = intf_id
        switch.interfaces = {intf_id: intf}
        self.napp.liveness_manager.interfaces["some_id"] = intf
        content = {"switch": switch}
        event = KytosEvent(content=content)
        self.napp.on_switch_deleted(event)
        assert "some_id" in self.napp.liveness_manager.interfaces
        assert intf.id not in self.napp.liveness_manager.interfaces
        assert not self.napp.liveness_controller.delete_interfaces.call_count
