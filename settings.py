"""Settings for the of_lldp NApp."""
FLOW_VLAN_VID = 3799
FLOW_PRIORITY = 50000
POLLING_TIME = 3

FLOW_MANAGER_URL = 'http://localhost:8181/api/kytos/flow_manager/v2'
TOPOLOGY_URL = 'http://localhost:8181/api/kytos/topology/v3'

# Link liveness hello interval is the same as POLLING_TIME
# Link liveness dead interval is POLLING_TIME * LIVENESS_DEAD_MULTIPLIER
LIVENESS_DEAD_MULTIPLIER = 5
# Link liveness minimum number of hellos before considering liveness UP
LIVENESS_MIN_HELLOS_UP = 2

LLDP_LOOP_ACTIONS = ["log"]  # supported actions ["log", "disable"]
LLDP_IGNORED_LOOPS = {}  # ignored loops per dpid {"dpid": [[1, 2]]}
# LLDP_IGNORED_LOOPS can be overwritten by switch.metadata.ignored_loops
LLDP_LOOP_DEAD_MULTIPLIER = 5
# Loop detection dead interval is POLLING_TIME * LIVENESS_DEAD_MULTIPLIER

LOOP_LOG_EVERY = int(max(900 / max(POLLING_TIME, 1), 1))  # 5 mins by default

# Prefix this NApp has when using cookies
COOKIE_PREFIX = 0xab

TABLE_GROUP_ALLOWED = {"base"}
