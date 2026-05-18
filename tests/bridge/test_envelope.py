"""Tests for envelope module."""

from batho.bridge.envelope import err, ok, to_json, ERROR_CODES


class TestEnvelope:
    """Test envelope helpers."""

    def test_ok_basic(self):
        """Basic ok envelope."""
        result = ok({"foo": "bar"})
        assert result["ok"] is True
        assert result["data"] == {"foo": "bar"}
        assert "workspace_id" not in result

    def test_ok_with_workspace(self):
        """Ok envelope with workspace_id."""
        result = ok({"foo": "bar"}, workspace_id="test-ws")
        assert result["ok"] is True
        assert result["workspace_id"] == "test-ws"

    def test_ok_with_meta(self):
        """Ok envelope with meta."""
        result = ok({"foo": "bar"}, meta={"duration_ms": 100})
        assert result["ok"] is True
        assert result["meta"] == {"duration_ms": 100}

    def test_err_basic(self):
        """Basic error envelope."""
        result = err("workspace_not_found", "Workspace not found")
        assert result["ok"] is False
        assert result["error"]["code"] == "workspace_not_found"
        assert result["error"]["message"] == "Workspace not found"

    def test_err_with_detail(self):
        """Error envelope with detail."""
        result = err("internal_error", "Something went wrong", detail={"extra": "info"})
        assert result["ok"] is False
        assert result["error"]["detail"] == {"extra": "info"}

    def test_err_with_workspace(self):
        """Error envelope with workspace_id."""
        result = err("workspace_not_found", "Not found", workspace_id="test-ws")
        assert result["workspace_id"] == "test-ws"

    def test_to_json(self):
        """JSON serialization."""
        result = ok({"foo": "bar"})
        json_str = to_json(result)
        assert '"ok": true' in json_str
        assert '"foo": "bar"' in json_str

    def test_error_codes_exist(self):
        """Error codes are defined."""
        assert "workspace_not_found" in ERROR_CODES
        assert "workspace_not_ready" in ERROR_CODES
        assert "artifact_not_found" in ERROR_CODES
        assert "invalid_argument" in ERROR_CODES
        assert "internal_error" in ERROR_CODES
