"""NApp responsible to discover new switches and hosts."""
import struct
from threading import Lock

import httpx
import tenacity
from napps.kytos.of_core.msg_prios import of_msg_prio
from napps.kytos.of_lldp import constants, settings
from napps.kytos.of_lldp.managers import LivenessManager, LoopManager
from napps.kytos.of_lldp.managers.loop_manager import LoopState
from napps.kytos.of_lldp.utils import (get_cookie, try_to_gen_intf_mac,
                                       update_flow)
from pyof.foundation.basic_types import DPID, UBInt32
from pyof.foundation.network_types import LLDP, VLAN, Ethernet, EtherType
from pyof.v0x04.common.action import ActionOutput as AO13
from pyof.v0x04.common.port import PortNo as Port13
from pyof.v0x04.controller2switch.packet_out import PacketOut as PO13
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_combine, wait_fixed, wait_random)

from kytos.core import KytosEvent, KytosNApp, log, rest
from kytos.core.exceptions import KytosTagError
from kytos.core.helpers import alisten_to, listen_to
from kytos.core.link import Link
from kytos.core.rest_api import (HTTPException, JSONResponse, Request,
                                 aget_json_or_400, get_json_or_400)
from kytos.core.retry import before_sleep
from kytos.core.switch import Switch

from .controllers import LivenessController


class Main(KytosNApp):
    """Main OF_LLDP NApp Class."""

    def setup(self):
        """Make this NApp run in a loop."""
        self.vlan_id = None
        self.polling_time = settings.POLLING_TIME
        if hasattr(settings, "FLOW_VLAN_VID"):
            self.vlan_id = settings.FLOW_VLAN_VID
        self.liveness_dead_multipler = settings.LIVENESS_DEAD_MULTIPLIER
        self.execute_as_loop(self.polling_time)
        self.loop_manager = LoopManager(self.controller)
        self.dead_interval = self.polling_time * self.liveness_dead_multipler
        self.liveness_controller = self.get_liveness_controller()
        self.liveness_controller.bootstrap_indexes()
        self.liveness_manager = LivenessManager(self.controller)
        self._liveness_ops_lock = Lock()
        Link.register_status_func(f"{self.napp_id}_liveness",
                                  LivenessManager.link_status_hook_liveness)
        status_reason_func = LivenessManager.link_status_reason_hook_liveness
        Link.register_status_reason_func(f"{self.napp_id}_liveness",
                                         status_reason_func)
        self.table_group = {"base": 0}

    @staticmethod
    def get_liveness_controller() -> LivenessController:
        """Get LivenessController."""
        return LivenessController()

    def execute(self):
        """Send LLDP Packets every 'POLLING_TIME' seconds to all switches."""
        switches = list(self.controller.switches.values())
        for switch in switches:
            try:
                of_version = switch.connection.protocol.version
            except AttributeError:
                of_version = None

            if not switch.is_connected():
                continue

            if of_version == 0x04:
                port_type = UBInt32
                local_port = Port13.OFPP_LOCAL
            else:
                # skip the current switch with unsupported OF version
                continue

            interfaces = list(switch.interfaces.values())
            for interface in interfaces:
                # Interface marked to receive lldp packet
                # Only send LLDP packet to active interface
                if (not interface.lldp or not interface.is_active()
                   or not interface.is_enabled()):
                    continue
                # Avoid the interface that connects to the controller.
                if interface.port_number == local_port:
                    continue

                lldp = LLDP()
                lldp.chassis_id.sub_value = DPID(switch.dpid)
                lldp.port_id.sub_value = port_type(interface.port_number)

                src_addr = try_to_gen_intf_mac(interface.address, switch.id,
                                               interface.port_number)
                ethernet = Ethernet()
                ethernet.ether_type = EtherType.LLDP
                ethernet.source = src_addr
                ethernet.destination = constants.LLDP_MULTICAST_MAC
                ethernet.data = lldp.pack()
                # self.vlan_id == None will result in a packet with no VLAN.
                ethernet.vlans.append(VLAN(vid=self.vlan_id))

                packet_out = self._build_lldp_packet_out(
                                    of_version,
                                    interface.port_number, ethernet.pack())

                if packet_out is None:
                    continue

                event_out = KytosEvent(
                    name='kytos/of_lldp.messages.out.ofpt_packet_out',
                    priority=of_msg_prio(packet_out.header.message_type.value),
                    content={
                            'destination': switch.connection,
                            'message': packet_out})

                self.controller.buffers.msg_out.put(event_out)
                log.debug(
                    "Sending a LLDP PacketOut to the switch %s",
                    switch.dpid)

                msg = 'Switch: %s (%s)'
                msg += ' Interface: %s'
                msg += ' -- LLDP PacketOut --'
                msg += ' Ethernet: eth_type (%s) | src (%s) | dst (%s) /'
                msg += ' LLDP: Switch (%s) | portno (%s)'

                log.debug(
                    msg,
                    switch.connection, switch.dpid,
                    interface.id, ethernet.ether_type,
                    ethernet.source, ethernet.destination,
                    switch.dpid, interface.port_number)

        self.try_to_publish_stopped_loops()
        self.liveness_manager.reaper(self.dead_interval)

    def load_liveness(self) -> None:
        """Load liveness."""
        enabled_intf_ids = {
            intf["id"]
            for intf in self.liveness_controller.get_enabled_interfaces()
        }
        intfs_to_enable = [
            intf
            for intf in self._get_interfaces()
            if intf.id in enabled_intf_ids
        ]
        self.liveness_manager.enable(*intfs_to_enable)

    def try_to_publish_stopped_loops(self):
        """Try to publish current stopped loops."""
        for dpid, port_pairs in self.loop_manager.get_stopped_loops().items():
            try:
                switch = self.controller.get_switch_by_dpid(dpid)
                for port_pair in port_pairs:
                    interface_a = switch.interfaces[port_pair[0]]
                    interface_b = switch.interfaces[port_pair[1]]
                    self.loop_manager.publish_loop_state(
                        interface_a, interface_b, LoopState.stopped.value
                    )
            except (KeyError, AttributeError) as exc:
                log.error("try_to_publish_stopped_loops failed with switch:"
                          f"{dpid}, port_pair: {port_pair}. {str(exc)}")

    @listen_to('kytos/topology.switch.(enabled|disabled)')
    def handle_lldp_flows(self, event):
        """Install or remove flows in a switch.

        Install a flow to send LLDP packets to the controller. The proactive
        flow is installed whenever a switch is enabled. If the switch is
        disabled the flow is removed.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                Event with new switch information.

        """
        self._handle_lldp_flows(event)

    @alisten_to("kytos/of_lldp.loop.action.log")
    async def on_lldp_loop_log_action(self, event: KytosEvent):
        """Handle LLDP loop log action."""
        interface_a = event.content["interface_a"]
        interface_b = event.content["interface_b"]
        await self.loop_manager.handle_log_action(interface_a, interface_b)

    @alisten_to("kytos/of_lldp.loop.action.disable")
    async def on_lldp_loop_disable_action(self, event: KytosEvent):
        """Handle LLDP loop disable action."""
        interface_a = event.content["interface_a"]
        interface_b = event.content["interface_b"]
        await self.loop_manager.handle_disable_action(interface_a, interface_b)

    @alisten_to("kytos/of_lldp.loop.stopped")
    async def on_lldp_loop_stopped(self, event: KytosEvent):
        """Handle LLDP loop stopped."""
        dpid = event.content["dpid"]
        port_pair = event.content["port_numbers"]
        try:
            switch = self.controller.get_switch_by_dpid(dpid)
            interface_a = switch.interfaces[port_pair[0]]
            interface_b = switch.interfaces[port_pair[1]]
            await self.loop_manager.handle_loop_stopped(interface_a,
                                                        interface_b)
        except (KeyError, AttributeError) as exc:
            log.error("on_lldp_loop_stopped failed with: "
                      f"{event.content} {str(exc)}")

    @alisten_to("kytos/topology.topology_loaded")
    async def on_topology_loaded(self, event):
        """Handle on topology loaded."""
        topology = event.content["topology"]
        await self.loop_manager.handle_topology_loaded(topology)
        self.load_liveness()

    @listen_to("kytos/topology.switch.deleted")
    def handle_switch_deleted(self, event: KytosEvent) -> None:
        """Handle on switch deleted."""
        with self._liveness_ops_lock:
            self.on_switch_deleted(event)

    def on_switch_deleted(self, event: KytosEvent) -> None:
        """Handle on switch deleted."""
        switch = event.content["switch"]
        found_intfs = []
        for intf in list(switch.interfaces.values()):
            if intf.id in self.liveness_manager.interfaces:
                found_intfs.append(intf)
        if found_intfs:
            intf_ids = [intf.id for intf in found_intfs]
            log.info(
                f"Disabling liveness on {switch} with interfaces "
                f" deleted {intf_ids} "
            )
            self.liveness_manager.disable(*found_intfs)
            self.liveness_controller.delete_interfaces(intf_ids)

    @listen_to("kytos/topology.interface.deleted")
    def handle_interface_deleted(self, event: KytosEvent) -> None:
        """Handle on interface deleted."""
        with self._liveness_ops_lock:
            self.on_interface_deleted(event)

    def on_interface_deleted(self, event: KytosEvent) -> None:
        """Handle on interface deleted."""
        intf = event.content["interface"]
        if intf.id in self.liveness_manager.interfaces:
            log.info(f"Disabling liveness on {intf} deleted")
            self.liveness_manager.disable(intf)
            self.liveness_controller.delete_interface(intf.id)

    @alisten_to("kytos/topology.switches.metadata.(added|removed)")
    async def on_switches_metadata_changed(self, event):
        """Handle on switches metadata changed."""
        switch = event.content["switch"]
        await self.loop_manager.handle_switch_metadata_changed(switch)

    def _handle_lldp_flows(self, event):
        """Install or remove flows in a switch.

        Install a flow to send LLDP packets to the controller. The proactive
        flow is installed whenever a switch is enabled. If the switch is
        disabled the flow is removed.
        """
        try:
            dpid = event.content['dpid']
            switch = self.controller.get_switch_by_dpid(dpid)
            of_version = switch.connection.protocol.version
        except AttributeError:
            of_version = None

        try:
            installed_flows = self.get_flows_by_switch(switch.id)
        except tenacity.RetryError as err:
            msg = f"Error: {err.last_attempt.exception()} when "\
                   "obtaining flows."
            log.error(msg)
            return
        except ValueError as err:
            log.error(f"Error when getting flows, error: {err}")
            return

        flow = None
        if ("switch.enabled" in event.name and not installed_flows or
                "switch.disabled" in event.name and installed_flows):
            flow = self._build_lldp_flow(of_version, get_cookie(switch.dpid))

        if flow:
            data = {'flows': [flow]}
            try:
                self.send_flow(switch, event.name, data=data)
            except tenacity.RetryError as err:
                msg = f"Error: {err.last_attempt.exception()} when"\
                      f" sending flows to {switch.id}, {data}"
                log.error(msg)

    # pylint: disable=unexpected-keyword-arg
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_combine(wait_fixed(3), wait_random(min=2, max=7)),
        before_sleep=before_sleep,
        retry=retry_if_exception_type(httpx.RequestError),
        after=update_flow(),
    )
    def send_flow(self, switch, event_name, data=None):
        """Send flows to flow_manager to be installed/deleted"""
        endpoint = f'{settings.FLOW_MANAGER_URL}/flows/{switch.id}'
        client_error = {424, 404, 400}
        if event_name == 'kytos/topology.switch.enabled':
            for flow in data['flows']:
                flow.pop("cookie_mask", None)
            res = httpx.post(endpoint, json=data, timeout=10)
            if res.is_server_error or res.status_code in client_error:
                raise httpx.RequestError(res.text)
            self.use_vlan(switch)

        elif event_name == 'kytos/topology.switch.disabled':
            res = httpx.request("DELETE", endpoint, json=data, timeout=10)
            if res.is_server_error or res.status_code in client_error:
                raise httpx.RequestError(res.text)
            self.make_vlan_available(switch)

    def use_vlan(self, switch: Switch) -> None:
        """Use vlan from interface"""
        if self.vlan_id is None:
            return
        for interface_id in switch.interfaces:
            interface = switch.interfaces[interface_id]
            try:
                interface.use_tags(self.controller, self.vlan_id)
            except KytosTagError as err:
                log.error(err)

    def make_vlan_available(self, switch: Switch) -> None:
        """Makes vlan from interface available"""
        if self.vlan_id is None:
            return
        for interface_id in switch.interfaces:
            interface = switch.interfaces[interface_id]
            try:
                conflict = interface.make_tags_available(
                    self.controller, self.vlan_id
                )
                if conflict:
                    log.warning(f"Tags {conflict} was already available"
                                f" in {switch.id}:{interface_id}")
            except KytosTagError as err:
                log.error(err)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_combine(wait_fixed(3), wait_random(min=2, max=7)),
        before_sleep=before_sleep,
        retry=retry_if_exception_type(httpx.RequestError),
    )
    def get_flows_by_switch(self, dpid: str) -> dict:
        """Get of_lldp flows by switch"""
        start = settings.COOKIE_PREFIX << 56
        end = start | 0x00FFFFFFFFFFFFFF
        endpoint = f'{settings.FLOW_MANAGER_URL}/stored_flows?state='\
                   f'installed&cookie_range={start}&cookie_range={end}'\
                   f'&dpid={dpid}'
        res = httpx.get(endpoint)
        if res.is_server_error or res.status_code == 404:
            raise httpx.RequestError(res.text)
        if res.status_code == 400:
            raise ValueError(res.json()["description"])
        return res.json()

    @alisten_to('kytos/of_core.v0x04.messages.in.ofpt_packet_in')
    async def on_ofpt_packet_in(self, event):
        """Dispatch two KytosEvents to notify identified NNI interfaces.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                Event with an LLDP packet as data.

        """
        ethernet = self._unpack_non_empty(Ethernet, event.message.data)
        if ethernet.ether_type == EtherType.LLDP:
            try:
                lldp = self._unpack_non_empty(LLDP, ethernet.data)
                dpid = self._unpack_non_empty(DPID, lldp.chassis_id.sub_value)
            except struct.error:
                #: If we have a LLDP packet but we cannot unpack it, or the
                #: unpacked packet does not contain the dpid attribute, then
                #: we are dealing with a LLDP generated by someone else. Thus
                #: this packet is not useful for us and we may just ignore it.
                return

            switch_a = event.source.switch
            port_a = event.message.in_port
            switch_b = None
            port_b = None

            # in_port is currently an Int in v0x04.
            if isinstance(port_a, int):
                port_a = UBInt32(port_a)

            try:
                switch_b = self.controller.get_switch_by_dpid(dpid.value)
                port_type = UBInt32
                port_b = self._unpack_non_empty(port_type,
                                                lldp.port_id.sub_value)
            except AttributeError:
                log.debug("Couldn't find datapath %s.", dpid.value)

            # Return if any of the needed information are not available
            if not (switch_a and port_a and switch_b and port_b):
                return

            interface_a = switch_a.get_interface_by_port_no(port_a.value)
            interface_b = switch_b.get_interface_by_port_no(port_b.value)
            if not interface_a or not interface_b:
                return

            await self.loop_manager.process_if_looped(interface_a, interface_b)
            await self.liveness_manager.consume_hello_if_enabled(interface_a,
                                                                 interface_b)
            event_out = KytosEvent(name='kytos/of_lldp.interface.is.nni',
                                   content={'interface_a': interface_a,
                                            'interface_b': interface_b})
            await self.controller.buffers.app.aput(event_out)

    def notify_lldp_change(self, state, interface_ids):
        """Dispatch a KytosEvent to notify changes to the LLDP status."""
        content = {'attribute': 'LLDP',
                   'state': state,
                   'interface_ids': interface_ids}
        event_out = KytosEvent(name='kytos/of_lldp.network_status.updated',
                               content=content)
        self.controller.buffers.app.put(event_out)

    def publish_liveness_status(self, event_suffix, interfaces):
        """Dispatch a KytosEvent to publish liveness admin status."""
        content = {"interfaces": interfaces}
        name = f"kytos/of_lldp.liveness.{event_suffix}"
        event_out = KytosEvent(name=name, content=content)
        self.controller.buffers.app.put(event_out)

    def shutdown(self):
        """End of the application."""
        log.debug('Shutting down...')

    @staticmethod
    def _build_lldp_packet_out(version, port_number, data):
        """Build a LLDP PacketOut message.

        Args:
            version (int): OpenFlow version
            port_number (int): Switch port number where the packet must be
                forwarded to.
            data (bytes): Binary data to be sent through the port.

        Returns:
            PacketOut message for the specific given OpenFlow version, if it
                is supported.
            None if the OpenFlow version is not supported.

        """
        if version == 0x04:
            action_output_class = AO13
            packet_out_class = PO13
        else:
            log.info('Openflow version %s is not yet supported.', version)
            return None

        output_action = action_output_class()
        output_action.port = port_number

        packet_out = packet_out_class()
        packet_out.data = data
        packet_out.actions.append(output_action)

        return packet_out

    def _build_lldp_flow(self, version, cookie,
                         cookie_mask=0xffffffffffffffff):
        """Build a Flow message to send LLDP to the controller.

        Args:
            version (int): OpenFlow version.

        Returns:
            Flow dictionary message for the specific given OpenFlow version,
            if it is supported.
            None if the OpenFlow version is not supported.

        """
        flow = {}
        if version == 0x04:
            flow['actions'] = [{'action_type': 'output',
                                'port': Port13.OFPP_CONTROLLER}]
        else:
            return None

        match = {}
        self.set_flow_table_group_owner(flow)
        flow['priority'] = settings.FLOW_PRIORITY
        flow['cookie'] = cookie
        flow['cookie_mask'] = cookie_mask
        match['dl_type'] = EtherType.LLDP
        if self.vlan_id:
            match['dl_vlan'] = self.vlan_id
        flow['match'] = match

        return flow

    @staticmethod
    def _unpack_non_empty(desired_class, data):
        """Unpack data using an instance of desired_class.

        Args:
            desired_class (class): The class to be used to unpack data.
            data (bytes): bytes to be unpacked.

        Return:
            An instance of desired_class class with data unpacked into it.

        Raises:
            UnpackException if the unpack could not be performed.

        """
        obj = desired_class()

        if hasattr(data, 'value'):
            data = data.value

        obj.unpack(data)

        return obj

    def _get_data(self, request: Request) -> list:
        """Get request data."""
        data = get_json_or_400(request, self.controller.loop)
        return data.get('interfaces', [])

    def _get_interfaces(self):
        """Get all interfaces."""
        interfaces = []
        for switch in list(self.controller.switches.values()):
            interfaces += list(switch.interfaces.values())
        return interfaces

    @staticmethod
    def _get_interfaces_dict(interfaces):
        """Return a dict of interfaces."""
        return {inter.id: inter for inter in interfaces}

    def _get_lldp_interfaces(self):
        """Get interfaces enabled to receive LLDP packets."""
        return [inter.id for inter in self._get_interfaces() if inter.lldp]

    @rest('v1/interfaces', methods=['GET'])
    async def get_lldp_interfaces(self, _request: Request) -> JSONResponse:
        """Return all the interfaces that have LLDP traffic enabled."""
        return JSONResponse({"interfaces": self._get_lldp_interfaces()})

    @rest('v1/interfaces/disable', methods=['POST'])
    def disable_lldp(self, request: Request) -> JSONResponse:
        """Disables an interface to receive LLDP packets."""
        interface_ids = self._get_data(request)
        error_list = []  # List of interfaces that were not activated.
        changed_interfaces = []
        interface_ids = filter(None, interface_ids)
        interfaces = self._get_interfaces()
        intfs = []
        if not interfaces:
            raise HTTPException(404, detail="No interfaces were found.")
        interfaces = self._get_interfaces_dict(interfaces)
        for id_ in interface_ids:
            interface = interfaces.get(id_)
            if interface:
                interface.lldp = False
                changed_interfaces.append(id_)
                intfs.append(interface)
            else:
                error_list.append(id_)
        if changed_interfaces:
            self.notify_lldp_change('disabled', changed_interfaces)
            intf_ids = [intf.id for intf in intfs]
            with self._liveness_ops_lock:
                self.liveness_controller.disable_interfaces(intf_ids)
                self.liveness_manager.disable(*intfs)
            self.publish_liveness_status("disabled", intfs)
        if not error_list:
            return JSONResponse(
                "All the requested interfaces have been disabled.")

        # Return a list of interfaces that couldn't be disabled
        msg_error = "Some interfaces couldn't be found and deactivated: "
        return JSONResponse({msg_error: error_list}, status_code=400)

    @rest('v1/interfaces/enable', methods=['POST'])
    def enable_lldp(self, request: Request) -> JSONResponse:
        """Enable an interface to receive LLDP packets."""
        interface_ids = self._get_data(request)
        error_list = []  # List of interfaces that were not activated.
        changed_interfaces = []
        interface_ids = filter(None, interface_ids)
        interfaces = self._get_interfaces()
        if not interfaces:
            raise HTTPException(404, detail="No interfaces were found.")
        interfaces = self._get_interfaces_dict(interfaces)
        for id_ in interface_ids:
            interface = interfaces.get(id_)
            if interface:
                interface.lldp = True
                changed_interfaces.append(id_)
            else:
                error_list.append(id_)
        if changed_interfaces:
            self.notify_lldp_change('enabled', changed_interfaces)
        if not error_list:
            return JSONResponse(
                "All the requested interfaces have been enabled.")

        # Return a list of interfaces that couldn't be enabled
        msg_error = "Some interfaces couldn't be found and activated: "
        return JSONResponse({msg_error: error_list}, status_code=400)

    @rest("v1/liveness/enable", methods=["POST"])
    def enable_liveness(self, request: Request) -> JSONResponse:
        """Enable liveness link detection on interfaces."""
        intf_ids = self._get_data(request)
        if not intf_ids:
            raise HTTPException(400, "Interfaces payload is empty")
        interfaces = {intf.id: intf for intf in self._get_interfaces()}
        diff = set(intf_ids) - set(interfaces.keys())
        if diff:
            raise HTTPException(404, f"Interface IDs {diff} not found")

        intfs = [interfaces[_id] for _id in intf_ids]
        non_lldp = [intf.id for intf in intfs if not intf.lldp]
        if non_lldp:
            msg = f"Interface IDs {non_lldp} don't have LLDP enabled"
            raise HTTPException(400, msg)
        with self._liveness_ops_lock:
            self.liveness_controller.enable_interfaces(intf_ids)
            self.liveness_manager.enable(*intfs)
            self.publish_liveness_status("enabled", intfs)
        return JSONResponse({})

    @rest("v1/liveness/disable", methods=["POST"])
    def disable_liveness(self, request: Request) -> JSONResponse:
        """Disable liveness link detection on interfaces."""
        intf_ids = self._get_data(request)
        if not intf_ids:
            raise HTTPException(400, "Interfaces payload is empty")

        interfaces = {intf.id: intf for intf in self._get_interfaces()}
        diff = set(intf_ids) - set(interfaces.keys())
        if diff:
            raise HTTPException(404, f"Interface IDs {diff} not found")

        intfs = [interfaces[_id] for _id in intf_ids if _id in interfaces]
        with self._liveness_ops_lock:
            self.liveness_controller.disable_interfaces(intf_ids)
            self.liveness_manager.disable(*intfs)
            self.publish_liveness_status("disabled", intfs)
        return JSONResponse({})

    @rest("v1/liveness/", methods=["GET"])
    async def get_liveness_interfaces(self, request: Request) -> JSONResponse:
        """Get liveness interfaces."""
        args = request.query_params
        interface_id = args.get("interface_id")
        if interface_id:
            status, last_hello_at = self.liveness_manager.get_interface_status(
                interface_id
            )
            if not status:
                return {"interfaces": []}, 200
            body = {
                "interfaces": [
                    {
                        "id": interface_id,
                        "status": status,
                        "last_hello_at": last_hello_at,
                    }
                ]
            }
            return JSONResponse(body)
        interfaces = []
        for interface_id in list(self.liveness_manager.interfaces.keys()):
            status, last_hello_at = self.liveness_manager.get_interface_status(
                interface_id
            )
            interfaces.append({"id": interface_id, "status": status,
                              "last_hello_at": last_hello_at})
        return JSONResponse({"interfaces": interfaces})

    @rest("v1/liveness/pair", methods=["GET"])
    async def get_liveness_interface_pairs(self,
                                           _request: Request) -> JSONResponse:
        """Get liveness interface pairs."""
        pairs = []
        for entry in list(self.liveness_manager.liveness.values()):
            lsm = entry["lsm"]
            pair = {
                "interface_a": {
                    "id": entry["interface_a"].id,
                    "status": lsm.ilsm_a.state,
                    "last_hello_at": lsm.ilsm_a.last_hello_at,
                },
                "interface_b": {
                    "id": entry["interface_b"].id,
                    "status": lsm.ilsm_b.state,
                    "last_hello_at": lsm.ilsm_b.last_hello_at,
                },
                "status": lsm.state
            }
            pairs.append(pair)
        return JSONResponse({"pairs": pairs})

    @rest('v1/polling_time', methods=['GET'])
    async def get_time(self, _request: Request) -> JSONResponse:
        """Get LLDP polling time in seconds."""
        return JSONResponse({"polling_time": self.polling_time})

    @rest('v1/polling_time', methods=['POST'])
    async def set_time(self, request: Request) -> JSONResponse:
        """Set LLDP polling time."""
        # pylint: disable=attribute-defined-outside-init
        try:
            payload = await aget_json_or_400(request)
            polling_time = int(payload['polling_time'])
            if polling_time <= 0:
                msg = f"invalid polling_time {polling_time}, " \
                        "must be greater than zero"
                raise HTTPException(400, detail=msg)
            self.polling_time = polling_time
            self.execute_as_loop(self.polling_time)
            log.info("Polling time has been updated to %s"
                     " second(s), but this change will not be saved"
                     " permanently.", self.polling_time)
            return JSONResponse("Polling time has been updated.")
        except (ValueError, KeyError) as error:
            msg = f"This operation is not completed: {error}"
            raise HTTPException(400, detail=msg) from error

    def set_flow_table_group_owner(self,
                                   flow: dict,
                                   group: str = "base") -> dict:
        """Set owner, table_group and table_id"""
        flow["table_id"] = self.table_group[group]
        flow["owner"] = "of_lldp"
        flow["table_group"] = group
        return flow

    # pylint: disable=attribute-defined-outside-init
    @alisten_to("kytos/of_multi_table.enable_table")
    async def on_table_enabled(self, event):
        """Handle a recently table enabled.
        of_lldp only allows "base" as flow group
        """
        table_group = event.content.get("of_lldp", None)
        if not table_group:
            return
        for group in table_group:
            if group not in settings.TABLE_GROUP_ALLOWED:
                log.error(f'The table group "{group}" is not allowed for '
                          f'of_lldp. Allowed table groups are '
                          f'{settings.TABLE_GROUP_ALLOWED}')
                return
        self.table_group.update(table_group)
        content = {"group_table": self.table_group}
        event_out = KytosEvent(name="kytos/of_lldp.enable_table",
                               content=content)
        await self.controller.buffers.app.aput(event_out)
