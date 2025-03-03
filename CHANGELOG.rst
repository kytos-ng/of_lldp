#########
Changelog
#########
All notable changes to the of_lldp NApp will be documented in this file.

[UNRELEASED] - Under development
********************************

[2024.1.1] - 2025-03-03
***********************

Fixed
=====
- DB controller now retries for ``ExecutionTimeout`` and ``ConnectionFailure`` instead of just ``AutoReconnect``

[2024.1.0] - 2024-07-23
***********************

Changed
=======
- Updated python environment installation from 3.9 to 3.11

[2023.2.0] - 2024-02-16
***********************

Changed
=======
- ``FLOW_VLAN_VID`` from settings now is used or made available in all interfaces from the switch where a flow is created or deleted.

[2023.1.0] - 2023-06-05
***********************

Changed
=======
- ``of_lldp`` now supports table group settings from ``of_multi_table``
- ``settings.TABLE_ID`` is no longer supported, ``table_id`` is managed by ``of_multi_table``
- When sending a PacketOut, if a interface's MAC address is invalid (all zeros or isn't an unicast address) it'll generate a new MAC address (last 40 bits of the DPID + interpolated port 8 bits + setting ``e`` in the nibble of the most significant byte to ensure unicast + locally administered)
- Raised defaultt ``settings.FLOW_PRIORITY`` to 50000.
- Refactored loop detection handlers to run on ``asyncio`` event loop instead of ``app`` thread pool, minimizing potential events starvation
- ``of_lldp`` when detecting a loop, it'll only set metadata in memory minimizing latency

Added
=====
- Subscribed to new event ``kytos/of_multi_table.enable_table`` as well as publishing ``kytos/of_lldp.enable_table`` required to set a different ``table_id`` to flows.
- Added ``settings.TABLE_GROUP_ALLOWED`` set containing the allowed table groups, for now there is only ``'base'``.

General Information
===================
- ``@rest`` endpoints are now run by ``starlette/uvicorn`` instead of ``flask/werkzeug``.
- To clean up lldp flows with the old priority, run the following command, then restart kytos: ``curl -H 'Content-type: application/json' -X DELETE http://127.0.0.1:8181/api/kytos/flow_manager/v2/flows/ -d '{"flows": [{"cookie": 12321848580485677056, "cookie_mask": 18374686479671623680}]}'``
- ``topology``'s ``settings.LINK_UP_TIMER`` is recommend to always be greater than ``of_lldp`` ``settings.POLLING_TIME`` (by default, it is), that way, it's always guaranteed that before a ``kytos/topology.link_up`` event is sent, then any looped metadata will have been already set.

[2022.3.0] - 2022-12-15
***********************

Removed
=======
- Removed support for OpenFlow 1.0

Fixed
=====
- Added early return when trying to process a loop or consume liveness in case interfaces haven't been created yet.

[2022.2.0] - 2022-08-05
***********************

Added
=====

- Loop detection in the same switch via LLDP ``ofpt_packet_in`` supporting ``log`` and ``disable`` actions
- Added settings for loop detection ``LLDP_LOOP_ACTIONS``, ``LLDP_IGNORED_LOOPS``, ``LLDP_LOOP_DEAD_MULTIPLIER``, ``LOOP_LOG_EVERY``
- Link liveness detection via LLDP
- Added settings for link liveness detection ``LIVENESS_DEAD_MULTIPLIER``
- Liveness detection endpoints ``GET /v1/liveness/``, ``GET /v1/liveness/pair``, ``POST /v1/liveness/enable``, ``POST /v1/liveness/disable``
- Hooked link liveness status function to influence ``Link.status``
- Added `liveness` collection to persist liveness interface configuration 

Changed
=======

- KytosEvent PacketOut is now being prioritized on ``msg_out``

[2022.1.0] - 2022-02-02
***********************

Changed
=======
- New versioning schema, following kytos core versioning


[1.3.1] - 2022-01-21
********************

Changed
=======
- Prefix changed to 0xab
- Upgraded dependencies
- Updated README referring Kytos NG


[1.3.0] - 2021-12-20
********************

Added
=====
- Set ``cookie`` and ``cookie_mask`` when sending requests to ``flow_manager``


[1.2.0] - 2021-12-13
********************
Changed
=======
- Added support for retries when sending a request to ``flow_manager``
- Parametrized ``force`` option as a fallback
- Added more logs for request errors


[1.1.1] - 2021-04-22
********************
Changed
=======
- Changed the description of the REST endpoint ``polling_time`` in the API
  documentation, describing that the change made at runtime is not persistent.
- Added ``kytos/topology`` as a dependency.


[1.1] - 2020-12-23
******************
Changed
=======
- Make ``of_lldp`` install and remove LLDP flows
  through the ``flow_manager`` NApp.
- Changed setup.py to alert when a test fails on Travis.


[1.0] - 2020-07-23
******************
Added
=====
- Added persistence module to store LLDP administrative changes.
- Added a REST endpoint to change LLDP polling_time at run time.
- Added unit tests, increasing coverage to 94%.
- Added tags decorator to run tests by type and size.
- Added support for automated tests and CI with Travis.


[0.1.4] - 2020-03-11
********************

Changed
=======
- Changed README.rst to include some info badges.

Fixed
=====
- Fixed `openapi.yml` file name.
- Fixed Scrutinizer coverage error.


[0.1.3] - 2019-08-30
********************

Added
=====
 - Added REST API to choose interfaces for sending LLDP packets.


[0.1.2] - 2019-03-15
********************

Added
=====
 - Continuous integration enabled at scrutinizer.

Fixed
=====
 - Fixed some linter issues.


[0.1.1] - 2018-04-20
********************
Added
=====
- Added REST API section
- Added try statement to notify_uplink method
- Added option to work with VLANs in LLDP exchanges.
- Added methods to send LLDP specific FlowMods.
- Avoid sending PacketOut to the 'OFPP_LOCAL' port.
- Choose port type according to OFP version.
- Make LLDP listen to v0x04 PacketIns too.
- Dispatch 'switch.link' event.
- Assure in_port has a value property.

Changed
=======
- Change Ethernet VLAN to list of VLANs.
