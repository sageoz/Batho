import pytest
from pathlib import Path
from batho.bridge.snippets import generate_agent_snippet, SUPPORTED_AGENTS
from batho.bridge.models import HubConfig, ServerConfig, WorkspaceConfig

@pytest.fixture
def sample_config():
    return HubConfig(
        server=ServerConfig(bind="127.0.0.1", http_port=8770, rest_port=8771),
        workspaces=[
            WorkspaceConfig(
                id="test-ws",
                ctn_dir="/tmp/.ctn",
                label="Test Workspace",
                enabled=True,
            )
        ],
    )

@pytest.mark.parametrize("agent", SUPPORTED_AGENTS)
def test_generate_snippet_valid_agent(agent, sample_config):
    result = generate_agent_snippet(agent, sample_config)
    assert result is not None
    assert "batho" in result.lower()

def test_generate_snippet_invalid_agent(sample_config):
    result = generate_agent_snippet("unknown_agent", sample_config)
    assert result is None

def test_claude_desktop_uses_stdio(sample_config):
    result = generate_agent_snippet("claude_desktop", sample_config)
    assert "stdio" in result
    assert "args" in result
    assert "mcpServers" in result

def test_cursor_uses_stdio(sample_config):
    result = generate_agent_snippet("cursor", sample_config)
    assert "args" in result
    assert "mcpServers" in result

def test_generic_uses_http(sample_config):
    result = generate_agent_snippet("generic", sample_config)
    assert "http://127.0.0.1:8770" in result
    assert "transport" in result
    assert "http" in result.lower()

def test_claude_desktop_sse(sample_config):
    result = generate_agent_snippet("claude_desktop", sample_config, transport="sse")
    assert "sse" in result
    assert "http://127.0.0.1:8770/sse" in result

def test_cursor_sse(sample_config):
    result = generate_agent_snippet("cursor", sample_config, transport="sse")
    assert "url" in result
    assert "http://127.0.0.1:8770/sse" in result
