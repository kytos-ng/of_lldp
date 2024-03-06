"""LivenessController."""

# pylint: disable=invalid-name
import os
from datetime import datetime
from typing import List

import pymongo
from pymongo.errors import AutoReconnect
from pymongo.operations import UpdateOne
from tenacity import retry_if_exception_type, stop_after_attempt, wait_random

from kytos.core import log
from kytos.core.db import Mongo
from kytos.core.retry import before_sleep, for_all_methods, retries

from ..db.models import LivenessDoc


@for_all_methods(
    retries,
    stop=stop_after_attempt(
        int(os.environ.get("MONGO_AUTO_RETRY_STOP_AFTER_ATTEMPT", 3))
    ),
    wait=wait_random(
        min=int(os.environ.get("MONGO_AUTO_RETRY_WAIT_RANDOM_MIN", 0.1)),
        max=int(os.environ.get("MONGO_AUTO_RETRY_WAIT_RANDOM_MAX", 1)),
    ),
    before_sleep=before_sleep,
    retry=retry_if_exception_type((AutoReconnect,)),
)
class LivenessController:
    """LivenessController."""

    def __init__(self, get_mongo=lambda: Mongo()) -> None:
        """LivenessController."""
        self.mongo = get_mongo()
        self.db_client = self.mongo.client
        self.db = self.db_client[self.mongo.db_name]

    def bootstrap_indexes(self) -> None:
        """Bootstrap all topology related indexes."""
        index_tuples = [
            ("liveness", [("enabled", pymongo.ASCENDING)]),
        ]
        for collection, keys in index_tuples:
            if self.mongo.bootstrap_index(collection, keys):
                log.info(f"Created DB index {keys}, collection: {collection})")

    def get_enabled_interfaces(self) -> List[dict]:
        """Get enabled liveness interfaces from DB."""
        return self.db.liveness.aggregate(
            [
                {"$match": {"enabled": True}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0}},
            ]
        )

    def upsert_interfaces(
        self,
        interface_ids: List[str],
        interface_dicts: List[dict],
        upsert=True,
    ) -> int:
        """Update or insert liveness interfaces."""
        utc_now = datetime.utcnow()
        ops = []
        for interface_id, interface_dict in zip(
            interface_ids, interface_dicts
        ):
            model = LivenessDoc(
                **{
                    **interface_dict,
                    **{"_id": interface_id, "updated_at": utc_now},
                }
            )
            payload = model.model_dump(
                exclude={"inserted_at"}, exclude_none=True
            )
            ops.append(
                UpdateOne(
                    {"_id": interface_id},
                    {
                        "$set": payload,
                        "$setOnInsert": {"inserted_at": utc_now},
                    },
                    upsert=upsert,
                )
            )
        response = self.db.liveness.bulk_write(ops)
        return response.upserted_count or response.modified_count

    def enable_interfaces(self, interface_ids: List[str]) -> int:
        """Enable liveness interfaces."""
        return self.upsert_interfaces(
            interface_ids,
            [{"enabled": True} for _ in interface_ids],
            upsert=True,
        )

    def disable_interfaces(self, interface_ids: List[str]) -> int:
        """Disable liveness interfaces."""
        return self.upsert_interfaces(
            interface_ids,
            [{"enabled": False} for _ in interface_ids],
            upsert=False,
        )
