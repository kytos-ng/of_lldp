"""Settings for the of_lldp NApp."""
FLOW_VLAN_VID = 3799
FLOW_PRIORITY = 1000
TABLE_ID = 0
POLLING_TIME = 3

FLOW_MANAGER_URL = 'http://localhost:8181/api/kytos/flow_manager/v2'
TOPOLOGY_URL = 'http://localhost:8181/api/kytos/topology/v3'

LLDP_LOOP_ACTIONS = ["log"]  # supported actions ["log", "disable"]
LLDP_IGNORED_LOOPS = {}  # ignored loops per dpid {"dpid": [[1, 2]]}
# LLDP_IGNORED_LOOPS can be overwritten by switch.metadata.ignored_loops

LOOP_LOG_EVERY = int(max(900 / max(POLLING_TIME, 1), 1))  # 5 mins by default

# Prefix this NApp has when using cookies
COOKIE_PREFIX = 0xab
