import os
import aiohttp

API_URL = os.getenv("API_URL")
API_TOKEN = os.getenv("API_TOKEN")

async def get_vps_server_status():
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL, headers=headers) as response:  # type: ignore
            if response.status == 200:
                return await response.json()
            return {"error": f"{response.status}: {await response.text()}"}


async def api_request(action: str):
    """Общая функция для API-запросов"""
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
    json_data = {"Type": action}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{API_URL}/Action", headers=headers, json=json_data) as response:
                if response.status == 200:
                    return await response.json()
                error_text = await response.text()
                return {"error": f"API error {response.status}: {error_text}"}
    except Exception as e:
        return {"error": f"Connection error: {str(e)}"}