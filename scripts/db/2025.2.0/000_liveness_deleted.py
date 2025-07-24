#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import pymongo

from napps.kytos.of_lldp.controllers import LivenessController

liveness_controller = LivenessController()


def list_liveness_non_existent(liveness_controller: LivenessController) -> list[dict]:
    """List liveness documents which don't exist on switches.interfaces docs."""
    db = liveness_controller.db
    return list(
        db.liveness.find({"_id": {"$nin": db.switches.distinct("interfaces.id")}})
    )


def delete_liveness_non_existent(liveness_controller: LivenessController) -> int:
    """Delete liveness documents which don't exist on switches.interfaces docs."""
    db = liveness_controller.db
    return db.liveness.delete_many(
        {"_id": {"$nin": db.switches.distinct("interfaces.id")}}
    ).deleted_count


if __name__ == "__main__":
    cmds = {
        "list": lambda: list_liveness_non_existent(liveness_controller),
        "delete": lambda: f"Deleted {delete_liveness_non_existent(liveness_controller)} document(s)",
    }
    try:
        cmd = os.environ["CMD"]
    except KeyError:
        print("Please set the 'CMD' env var.")
        sys.exit(1)
    try:
        for command in cmd.split(","):
            print(cmds[command]())
    except KeyError as e:
        print(
            f"Unknown cmd: {str(e)}. 'CMD' env var has to be one of these {list(cmds.keys())}."
        )
        sys.exit(1)
    except pymongo.errors.PyMongoError as e:
        print(f"pymongo error: {str(e)}")
        sys.exit(1)
