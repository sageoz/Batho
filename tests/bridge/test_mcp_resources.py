import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from batho.bridge.hub import create_hub
from batho.bridge.models import WorkspaceConfig, WorkspaceState

@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.list.return_value = [
        WorkspaceConfig(id="test-ws", label="Test Workspace", ctn_dir="/tmp/.ctn", enabled=True)
    ]
    
    handle = MagicMock()
    handle.workspace_id = "test-ws"
    handle.is_ready = True
    handle.artifact_count = 100
    handle.last_index_time = 1705300000.0
    handle.get_index = AsyncMock(return_value={"entities": []})
    
    manager.resolve = AsyncMock(return_value=handle)
    manager.get.return_value = handle
    manager.get_handle.return_value = handle
    
    return manager

@pytest.mark.asyncio
async def test_workspace_resource_returns_index(mock_manager):
    mcp = create_hub(mock_manager)
    
    template_found = False
    for template in mcp._resource_manager._templates.values():
        if template.uri_template == "batho://workspace/{workspace_id}/index.json":
            template_found = True
            # ResourceTemplate.fn is the underlying function
            result = await template.fn(workspace_id="test-ws")
            assert "entities" in result
            break
    
    assert template_found

@pytest.mark.asyncio
async def test_workspaces_list_resource(mock_manager):
    mcp = create_hub(mock_manager)
    
    resource_found = False
    resource_uris = [r.uri for r in mcp._resource_manager._resources.values()]
    template_uris = [t.uri_template for t in mcp._resource_manager._templates.values()]
    
    for resource in mcp._resource_manager._resources.values():
        if str(resource.uri) == "batho://workspaces/list":
            resource_found = True
            result = await resource.fn()
            workspaces = json.loads(result)
            assert isinstance(workspaces, list)
            assert len(workspaces) == 1
            assert workspaces[0]["id"] == "test-ws"
            assert workspaces[0]["artifact_count"] == 100
            break
            
    assert resource_found, f"Resource not found. Available resources: {resource_uris}, templates: {template_uris}"

@pytest.mark.asyncio
async def test_prompts_registered(mock_manager):
    mcp = create_hub(mock_manager)
    
    prompt_names = {p.name for p in mcp._prompt_manager._prompts.values()}
    assert "find_symbol" in prompt_names
    assert "summarise_workspace" in prompt_names
    assert "cross_repo_search" in prompt_names
