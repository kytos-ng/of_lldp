"""Settings for the of_lldp NApp."""
FLOW_VLAN_VID = 3799
FLOW_PRIORITY = 1000
TABLE_ID = 0
POLLING_TIME = 3

FLOW_MANAGER_URL = 'http://localhost:8181/api/kytos/flow_manager/v2'

LLDP_LOOP_ACTION = "log"  # supportted actions ["log"]
LLDP_IGNORED_LOOPS = {}  # ignored loops per dpid {"dpid": {(1, 2)}}
LOOP_LOG_EVERY = max(60 / max(POLLING_TIME, 1), 1)  # every minute by default
