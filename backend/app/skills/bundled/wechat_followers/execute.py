from __future__ import annotations

import httpx

from skill_lib.wechat_auth import get_access_token

_BASE = "https://api.weixin.qq.com/cgi-bin"


async def execute(next_openid: str = "") -> str:
    try:
        token = await get_access_token()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BASE}/user/get",
                params={"access_token": token, "next_openid": next_openid},
            )
            data = resp.json()

        if data.get("errcode"):
            return f"Error: {data.get('errmsg', 'Unknown error')} (code: {data.get('errcode')})"

        total = data.get("total", 0)
        count = data.get("count", 0)
        openids = data.get("data", {}).get("openid", [])
        next_id = data.get("next_openid", "")

        lines = [f"Total followers: {total}, this page: {count}"]
        for oid in openids[:20]:
            lines.append(f"  - {oid}")
        if next_id:
            lines.append(f"Next page cursor: {next_id}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Failed to list followers: {exc}"
