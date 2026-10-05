"""Optional official SDK transport, not activated or installed by the installer."""
import asyncio

ENDPOINT = "https://api.githubcopilot.com/mcp/"


class OfficialMCPTransport:
    def __init__(self, credential_provider):
        # Future Keychain host integration supplies this callable. No token in config/chat.
        self.credential_provider = credential_provider

    def __call__(self, name, arguments, timeout=30):
        if name not in {"get_file_contents", "create_or_update_file"}:
            raise ValueError("Forbidden MCP tool")
        return asyncio.run(asyncio.wait_for(self._call(name, arguments), timeout=timeout))

    async def _call(self, name, arguments):
        # Uses the supported v1 SDK interface; optional dependency mcp>=1.28,<2.
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        token = self.credential_provider()
        if not isinstance(token, str) or not token or any(ord(c) < 33 for c in token):
            raise ValueError("Credential unavailable")
        async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token,
                "X-MCP-Tools": "get_file_contents,create_or_update_file"},
                follow_redirects=False, trust_env=False, timeout=30) as http:
            async with streamable_http_client(ENDPOINT, http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    return result.model_dump(by_alias=True, exclude_none=True)
