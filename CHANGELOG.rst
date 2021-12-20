#########
Changelog
#########
All notable changes to the of_lldp NApp will be documented in this file.

[UNRELEASED] - Under development
********************************
Added
=====

Changed
=======

Deprecated
==========

Removed
=======

Fixed
=====

Security
========

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
