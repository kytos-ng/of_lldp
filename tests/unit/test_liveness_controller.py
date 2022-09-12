"""Module to test LivenessController."""
# pylint: disable=invalid-name,relative-beyond-top-level

from unittest.mock import MagicMock


class TestLivenessController:  # pylint: disable=too-many-public-methods
    """Test the Main class."""

    def test_boostrap_indexes(self, liveness_controller) -> None:
        """Test_boostrap_indexes."""
        liveness_controller.bootstrap_indexes()

        expected_indexes = [("liveness", [("enabled", 1)])]
        mock = liveness_controller.mongo.bootstrap_index
        assert mock.call_count == len(expected_indexes)
        indexes = [(v[0][0], v[0][1]) for v in mock.call_args_list]
        assert expected_indexes == indexes

    def test_get_enabled_interfaces(self, liveness_controller) -> None:
        """Test get_enabled_interfaces."""
        liveness_controller.get_enabled_interfaces()
        assert liveness_controller.db.liveness.aggregate.call_count == 1
        call_args = liveness_controller.db.liveness.aggregate.call_args
        assert call_args[0][0] == [
            {"$match": {"enabled": True}},
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0}},
        ]

    def test_upsert_interfaces(self, liveness_controller) -> None:
        """Test upsert_interfaces."""
        intf_ids = ["00:00:00:00:00:00:00:01:2", "00:00:00:00:00:00:00:02:2"]
        intf_dicts = [{"enabled": True}, {"enabled": True}]
        liveness_controller.upsert_interfaces(intf_ids, intf_dicts)
        assert liveness_controller.db.liveness.bulk_write.call_count == 1

    def test_enable_interfaces(self, liveness_controller) -> None:
        """Test enable_interfaces."""
        intf_ids = ["00:00:00:00:00:00:00:01:2", "00:00:00:00:00:00:00:02:2"]
        liveness_controller.upsert_interfaces = MagicMock()
        upsert_mock = liveness_controller.upsert_interfaces
        liveness_controller.enable_interfaces(intf_ids)
        assert upsert_mock.call_count == 1
        upsert_mock.assert_called_with(
            intf_ids,
            [{"enabled": True}, {"enabled": True}],
            upsert=True,
        )

    def test_disable_interfaces(self, liveness_controller) -> None:
        """Test disable_interfaces."""
        intf_ids = ["00:00:00:00:00:00:00:01:2", "00:00:00:00:00:00:00:02:2"]
        liveness_controller.upsert_interfaces = MagicMock()
        upsert_mock = liveness_controller.upsert_interfaces
        liveness_controller.disable_interfaces(intf_ids)
        assert upsert_mock.call_count == 1
        upsert_mock.assert_called_with(
            intf_ids,
            [{"enabled": False}, {"enabled": False}],
            upsert=False,
        )
