import asyncio

import pytest

from ai_accounts_core.pty.handle import AsyncPtyHandle


@pytest.mark.asyncio
async def test_echo_command():
    handle = await AsyncPtyHandle.spawn(command=("/bin/echo", "hello"), cols=80, rows=24)
    chunks: list[bytes] = []
    async for chunk in handle.read():
        chunks.append(chunk)
        if b"hello" in b"".join(chunks):
            break
    assert b"hello" in b"".join(chunks)
    await handle.close()


@pytest.mark.asyncio
async def test_write_to_interactive_shell():
    handle = await AsyncPtyHandle.spawn(command=("/bin/sh",), cols=80, rows=24)
    await handle.write(b"echo test123\n")
    chunks: list[bytes] = []
    deadline = asyncio.get_event_loop().time() + 3.0
    async for chunk in handle.read():
        chunks.append(chunk)
        if b"test123" in b"".join(chunks):
            break
        if asyncio.get_event_loop().time() > deadline:
            break
    assert b"test123" in b"".join(chunks)
    await handle.close()


@pytest.mark.asyncio
async def test_resize():
    handle = await AsyncPtyHandle.spawn(command=("/bin/sh",), cols=80, rows=24)
    await handle.resize(120, 40)
    await handle.close()
