"""
Tests for LSPProcessManager.
"""

import asyncio
import json
import pytest
import sys

from batho_core.context.lsp.process_manager import LSPProcessManager, LSPProcessState
from batho_core.context.lsp.errors import LSPProcessError


@pytest.mark.asyncio
async def test_process_lifecycle():
    # Use python as a mock command that just exits
    manager = LSPProcessManager([sys.executable, "-c", "import sys; sys.exit(0)"])
    
    assert manager.state == LSPProcessState.STOPPED
    
    await manager.start()
    assert manager.state == LSPProcessState.RUNNING
    
    # Wait for process to exit
    await asyncio.sleep(0.5)
    
    await manager.stop()
    assert manager.state == LSPProcessState.STOPPED


@pytest.mark.asyncio
async def test_invalid_command():
    manager = LSPProcessManager(["__this_command_does_not_exist_1234__"])
    
    with pytest.raises(LSPProcessError):
        await manager.start()
        
    assert manager.state == LSPProcessState.FAILED


@pytest.mark.asyncio
async def test_send_message_not_running():
    manager = LSPProcessManager([sys.executable])
    # Don't start it
    
    with pytest.raises(LSPProcessError):
        await manager.send_message({"jsonrpc": "2.0"})


@pytest.mark.asyncio
async def test_read_message_not_running():
    manager = LSPProcessManager([sys.executable])
    
    with pytest.raises(LSPProcessError):
        await manager.read_message()
