from typing import Any, Optional

import aiohttp

from streaming_providers.debrid_client import DebridClient
from streaming_providers.exceptions import ProviderException
from utils import const


class Torbox(DebridClient):
    BASE_URL = "https://api.torbox.app/v1/api"

    async def initialize_headers(self):
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.headers.update(const.NO_CACHE_HEADERS)

    async def disable_access_token(self):
        pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def _handle_service_specific_errors(self, error_data: dict, status_code: int):
        error_code = error_data.get("error")
        match error_code:
            case "BAD_TOKEN" | "AUTH_ERROR" | "OAUTH_VERIFICATION_ERROR":
                raise ProviderException(
                    "Invalid Torbox token",
                    "invalid_token.mp4",
                )
            case "DOWNLOAD_TOO_LARGE":
                raise ProviderException(
                    "Download size too large for the user plan",
                    "not_enough_space.mp4",
                )
            case "ACTIVE_LIMIT" | "MONTHLY_LIMIT" | "COOLDOWN_LIMIT":
                raise ProviderException(
                    "Download limit exceeded",
                    "daily_download_limit.mp4",
                )
            case "DOWNLOAD_SERVER_ERROR" | "DATABASE_ERROR":
                raise ProviderException(
                    "Torbox server error",
                    "debrid_service_down_error.mp4",
                )

    async def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        params = params or {}
        full_url = self.BASE_URL + url
        return await super()._make_request(
            method=method, url=full_url, params=params, **kwargs
        )

    async def add_magnet_link(self, magnet_link):
        response_data = await self._make_request(
            "POST",
            "/torrents/createtorrent",
            data={"magnet": magnet_link},
            is_expected_to_fail=True,
        )

        if response_data.get("error"):
            await self._handle_service_specific_errors(response_data, 200)
            raise ProviderException(
                f"Failed to add magnet link to Torbox {response_data}",
                "transfer_error.mp4",
            )
        return response_data

    async def add_torrent_file(self, torrent_file: bytes, torrent_name: Optional[str]):
        data = aiohttp.FormData()
        data.add_field(
            "file",
            torrent_file,
            filename=torrent_name,
            content_type="application/x-bittorrent",
        )
        response = await self._make_request(
            "POST",
            "/torrents/createtorrent",
            data=data,
            is_expected_to_fail=True,
        )
        if response.get("error"):
            await self._handle_service_specific_errors(response, 200)

            raise ProviderException(
                f"Failed to add torrent file to Torbox {response.get('error')}",
                "transfer_error.mp4",
            )
        return response

    async def get_user_torrent_list(self):
        response = await self._make_request(
            "GET",
            "/torrents/mylist",
            params={"bypass_cache": "true"},
            is_expected_to_fail=True,
        )
        if response.get("success"):
            return response
        return {"data": []}

    async def get_torrent_info(self, magnet_id):
        response = await self.get_user_torrent_list()
        torrent_list = response.get("data", [])
        for torrent in torrent_list:
            if torrent.get("magnet", "") == magnet_id:
                return torrent
        return {}

    async def get_torrent_instant_availability(self, torrent_hashes: list[str]):
        response = await self._make_request(
            "GET",
            "/torrents/checkcached",
            params={"hash": torrent_hashes, "format": "object"},
        )
        return response.get("data", [])

    async def get_available_torrent(self, info_hash) -> dict[str, Any] | None:
        response = await self.get_user_torrent_list()
        torrent_list = response.get("data", [])
        for torrent in torrent_list:
            if torrent.get("hash") == info_hash:
                return torrent
        return {}

    async def get_queued_torrents(self):
        response = await self._make_request(
            "GET",
            "/queued/getqueued",
            params={"type": "torrent", "bypass_cache": "true"},
        )
        return response

    async def create_download_link(
        self, torrent_id: int, file_id: int, user_ip: Optional[str]
    ) -> dict:
        params = {
            "token": self.token,
            "torrent_id": torrent_id,
            "file_id": file_id,
        }
        if user_ip:
            params["user_ip"] = user_ip
        response = await self._make_request(
            "GET",
            "/torrents/requestdl",
            params=params,
            is_expected_to_fail=True,
        )
        if response.get("success"):
            return response

        await self._handle_service_specific_errors(response, 200)
        raise ProviderException(
            f"Failed to create download link from Torbox {response}",
            "transfer_error.mp4",
        )

    async def delete_torrent(self, torrent_id):
        return await self._make_request(
            "POST",
            "/torrents/controltorrent",
            json={"torrent_id": torrent_id, "operation": "delete"},
        )

    async def get_user_info(self, get_settings: bool = False):
        return await self._make_request(
            "GET", "/user/me", params={"settings": "true" if get_settings else "false"}
        )
