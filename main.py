"""NApp responsible to discover new switches and hosts."""
import struct
import time
from collections import defaultdict
from threading import Lock

import requests
from flask import jsonify, request
from pyof.foundation.basic_types import DPID, UBInt16, UBInt32
from pyof.foundation.network_types import LLDP, VLAN, Ethernet, EtherType
from pyof.v0x01.common.action import ActionOutput as AO10
from pyof.v0x01.common.phy_port import Port as Port10
from pyof.v0x01.controller2switch.packet_out import PacketOut as PO10
from pyof.v0x04.common.action import ActionOutput as AO13
from pyof.v0x04.common.port import PortNo as Port13
from pyof.v0x04.controller2switch.packet_out import PacketOut as PO13

from kytos.core import KytosEvent, KytosNApp, log, rest
from kytos.core.helpers import listen_to
from napps.kytos.of_lldp import constants, settings


class Main(KytosNApp):
    """Main OF_LLDP NApp Class."""

    def setup(self):
        """Make this NApp run in a loop."""
        self.vlan_id = None
        self.polling_time = settings.POLLING_TIME
        self.ignored_loops = settings.LLDP_IGNORED_LOOPS
        self.counter_lock = Lock()
        self.loop_counter = defaultdict(dict)
        if hasattr(settings, "FLOW_VLAN_VID"):
            self.vlan_id = settings.FLOW_VLAN_VID
        self.execute_as_loop(self.polling_time)

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

            if of_version == 0x01:
                port_type = UBInt16
                local_port = Port10.OFPP_LOCAL
            elif of_version == 0x04:
                port_type = UBInt32
                local_port = Port13.OFPP_LOCAL
            else:
                # skip the current switch with unsupported OF version
                continue

            interfaces = list(switch.interfaces.values())
            for interface in interfaces:
                # Interface marked to receive lldp packet
                # Only send LLDP packet to active interface
                if(not interface.lldp or not interface.is_active()
                   or not interface.is_enabled()):
                    continue
                # Avoid the interface that connects to the controller.
                if interface.port_number == local_port:
                    continue

                lldp = LLDP()
                lldp.chassis_id.sub_value = DPID(switch.dpid)
                lldp.port_id.sub_value = port_type(interface.port_number)

                ethernet = Ethernet()
                ethernet.ether_type = EtherType.LLDP
                ethernet.source = interface.address
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

        def _retry_if_status_code(response, endpoint, data, status_codes,
                                  retries=3, wait=2):
            """Retry if the response is in the status_codes."""
            if response.status_code not in status_codes:
                return
            if retries - 1 <= 0:
                return
            data = dict(data)
            data["force"] = True
            res = requests.post(endpoint, json=data)
            method = res.request.method
            if res.status_code != 202:
                log.error(f"Failed to retry on {endpoint}, error: {res.text},"
                          f" status: {res.status_code}, method: {method},"
                          f" data: {data}")
                time.sleep(wait)
                return _retry_if_status_code(response, endpoint, data,
                                             status_codes, retries - 1, wait)
            log.info(f"Successfully forced {method} flows to {endpoint}")

        flow = self._build_lldp_flow(of_version)
        if flow:
            destination = switch.id
            endpoint = f'{settings.FLOW_MANAGER_URL}/flows/{destination}'
            data = {'flows': [flow]}
            if event.name == 'kytos/topology.switch.enabled':
                res = requests.post(endpoint, json=data)
                if res.status_code != 202:
                    log.error(f"Failed to push flows on {destination},"
                              f" error: {res.text}, status: {res.status_code},"
                              f" data: {data}")
                _retry_if_status_code(res, endpoint, data, [424, 500])
            else:
                res = requests.delete(endpoint, json=data)
                if res.status_code != 202:
                    log.error(f"Failed to delete flows on {destination},"
                              f" error: {res.text}, status: {res.status_code}",
                              f" data: {data}")
                _retry_if_status_code(res, endpoint, data, [424, 500])

    def _is_loop_ignored(self, dpid, port_a, port_b):
        """Check if a loop is ignored."""
        if dpid not in self.ignored_loops:
            return False
        if any(
            (
                (port_a, port_b) in self.ignored_loops[dpid],
                (port_b, port_a) in self.ignored_loops[dpid],
            )
        ):
            return True
        return False

    @staticmethod
    def _is_lldp_looped(dpid_a, port_a, dpid_b, port_b):
        """Check if LLDP is looped."""
        if all(
            (
                dpid_a == dpid_b,
                port_a <= port_b  # only enter one pair
            )
        ):
            return True
        return False

    def process_if_lldp_looped(
        self,
        switch_a,
        interface_a,
        switch_b,
        interface_b,
        action=settings.LLDP_LOOP_ACTION,
    ):
        """Process if received LLDP data is looped."""
        dpid_a = switch_a.dpid
        dpid_b = switch_b.dpid
        port_a = interface_a.port_number
        port_b = interface_b.port_number
        if all(
            (
                self._is_lldp_looped(dpid_a, port_a, dpid_b, port_b),
                not self._is_loop_ignored(dpid_a, port_a, port_b),
            )
        ):
            self.lldp_loop_handler(switch_a, interface_a, interface_b, action)

    def lldp_loop_handler(
        self,
        switch,
        interface_a,
        interface_b,
        action=settings.LLDP_LOOP_ACTION,
    ):
        """Handler to execute when a LLDP loop is found."""
        if action == "log":
            port_a = interface_a.port_number
            port_b = interface_b.port_number
            port_pair = (port_a, port_b)
            log_every = settings.LOOP_LOG_EVERY
            with self.counter_lock:
                if port_pair not in self.loop_counter[switch.id]:
                    self.loop_counter[switch.id][port_pair] = 0
                else:
                    self.loop_counter[switch.id][port_pair] += 1
                    self.loop_counter[switch.id][port_pair] %= log_every
                count = self.loop_counter[switch.id][port_pair]
                if count != 0:
                    return

            log.warning(
                f"LLDP loop detected on switch: {switch.id}, "
                f"interface_a: {interface_a.name}, number: {port_a}, "
                f"interface_b: {interface_b.name}, number: {port_b}"
            )

    @listen_to('kytos/of_core.v0x0[14].messages.in.ofpt_packet_in')
    def on_ofpt_packet_in(self, event):
        """Dispatch two KytosEvents to notify identified NNI interfaces.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                Event with an LLDP packet as data.

        """
        self.notify_uplink_detected(event)

    def notify_uplink_detected(self, event):
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

            # in_port is currently a UBInt16 in v0x01 and an Int in v0x04.
            if isinstance(port_a, int):
                port_a = UBInt32(port_a)

            try:
                switch_b = self.controller.get_switch_by_dpid(dpid.value)
                of_version = switch_b.connection.protocol.version
                port_type = UBInt16 if of_version == 0x01 else UBInt32
                port_b = self._unpack_non_empty(port_type,
                                                lldp.port_id.sub_value)
            except AttributeError:
                log.debug("Couldn't find datapath %s.", dpid.value)

            # Return if any of the needed information are not available
            if not (switch_a and port_a and switch_b and port_b):
                return

            interface_a = switch_a.get_interface_by_port_no(port_a.value)
            interface_b = switch_b.get_interface_by_port_no(port_b.value)

            self.process_if_lldp_looped(switch_a, interface_a, switch_b,
                                        interface_b)
            event_out = KytosEvent(name='kytos/of_lldp.interface.is.nni',
                                   content={'interface_a': interface_a,
                                            'interface_b': interface_b})
            self.controller.buffers.app.put(event_out)

    def notify_lldp_change(self, state, interface_ids):
        """Dispatch a KytosEvent to notify changes to the LLDP status."""
        content = {'attribute': 'LLDP',
                   'state': state,
                   'interface_ids': interface_ids}
        event_out = KytosEvent(name='kytos/of_lldp.network_status.updated',
                               content=content)
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
        if version == 0x01:
            action_output_class = AO10
            packet_out_class = PO10
        elif version == 0x04:
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

    def _build_lldp_flow(self, version):
        """Build a Flow message to send LLDP to the controller.

        Args:
            version (int): OpenFlow version.

        Returns:
            Flow dictionary message for the specific given OpenFlow version,
            if it is supported.
            None if the OpenFlow version is not supported.

        """
        flow = {}
        match = {}
        flow['priority'] = settings.FLOW_PRIORITY
        flow['table_id'] = settings.TABLE_ID
        match['dl_type'] = EtherType.LLDP
        if self.vlan_id:
            match['dl_vlan'] = self.vlan_id
        flow['match'] = match

        if version == 0x01:
            flow['actions'] = [{'action_type': 'output',
                                'port': Port10.OFPP_CONTROLLER}]
        elif version == 0x04:
            flow['actions'] = [{'action_type': 'output',
                                'port': Port13.OFPP_CONTROLLER}]
        else:
            flow = None

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

    @staticmethod
    def _get_data(req):
        """Get request data."""
        data = req.get_json()  # Valid format { "interfaces": [...] }
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
    def get_lldp_interfaces(self):
        """Return all the interfaces that have LLDP traffic enabled."""
        return jsonify({"interfaces": self._get_lldp_interfaces()}), 200

    @rest('v1/interfaces/disable', methods=['POST'])
    def disable_lldp(self):
        """Disables an interface to receive LLDP packets."""
        interface_ids = self._get_data(request)
        error_list = []  # List of interfaces that were not activated.
        changed_interfaces = []
        interface_ids = filter(None, interface_ids)
        interfaces = self._get_interfaces()
        if not interfaces:
            return jsonify("No interfaces were found."), 404
        interfaces = self._get_interfaces_dict(interfaces)
        for id_ in interface_ids:
            interface = interfaces.get(id_)
            if interface:
                interface.lldp = False
                changed_interfaces.append(id_)
            else:
                error_list.append(id_)
        if changed_interfaces:
            self.notify_lldp_change('disabled', changed_interfaces)
        if not error_list:
            return jsonify(
                "All the requested interfaces have been disabled."), 200

        # Return a list of interfaces that couldn't be disabled
        msg_error = "Some interfaces couldn't be found and deactivated: "
        return jsonify({msg_error:
                        error_list}), 400

    @rest('v1/interfaces/enable', methods=['POST'])
    def enable_lldp(self):
        """Enable an interface to receive LLDP packets."""
        interface_ids = self._get_data(request)
        error_list = []  # List of interfaces that were not activated.
        changed_interfaces = []
        interface_ids = filter(None, interface_ids)
        interfaces = self._get_interfaces()
        if not interfaces:
            return jsonify("No interfaces were found."), 404
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
            return jsonify(
                "All the requested interfaces have been enabled."), 200

        # Return a list of interfaces that couldn't be enabled
        msg_error = "Some interfaces couldn't be found and activated: "
        return jsonify({msg_error:
                        error_list}), 400

    @rest('v1/polling_time', methods=['GET'])
    def get_time(self):
        """Get LLDP polling time in seconds."""
        return jsonify({"polling_time": self.polling_time}), 200

    @rest('v1/polling_time', methods=['POST'])
    def set_time(self):
        """Set LLDP polling time."""
        # pylint: disable=attribute-defined-outside-init
        try:
            payload = request.get_json()
            polling_time = int(payload['polling_time'])
            if polling_time <= 0:
                raise ValueError(f"invalid polling_time {polling_time}, "
                                 "must be greater than zero")
            self.polling_time = polling_time
            self.execute_as_loop(self.polling_time)
            log.info("Polling time has been updated to %s"
                     " second(s), but this change will not be saved"
                     " permanently.", self.polling_time)
            return jsonify("Polling time has been updated."), 200
        except (ValueError, KeyError) as error:
            msg = f"This operation is not completed: {error}"
            return jsonify(msg), 400
