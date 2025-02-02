import asyncio
from typing import List, Optional

from fastapi import BackgroundTasks

from db.models import TorrentStreams
from db.schemas import UserData
from streaming_providers.exceptions import ProviderException
from streaming_providers.offcloud.client import OffCloud


async def get_video_url_from_offcloud(
    info_hash: str,
    magnet_link: str,
    user_data: UserData,
    background_tasks: BackgroundTasks,
    stream: Optional[TorrentStreams] = None,
    filename: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    max_retries: int = 5,
    retry_interval: int = 5,
    **kwargs,
) -> str:
    async with OffCloud(token=user_data.streaming_provider.token) as oc_client:
        # Check if the torrent already exists
        torrent_info = await oc_client.get_available_torrent(info_hash)
        if torrent_info:
            request_id = torrent_info.get("requestId")
            torrent_info = await oc_client.get_torrent_info(request_id)
            if torrent_info["status"] == "downloaded":
                login_to_oc(user_data)
                return await oc_client.create_download_link(
                    request_id,
                    torrent_info,
                    stream,
                    filename,
                    season,
                    episode,
                    background_tasks,
                )
            if torrent_info["status"] == "error":
                raise ProviderException(
                    f"Error transferring magnet link to OffCloud. {torrent_info['errorMessage']}",
                    "transfer_error.mp4",
                )
        else:
            '''
            # If torrent doesn't exist, add it
            if stream.torrent_file:
                response_data = await oc_client.add_torrent_file(
                    stream.torrent_file, stream.torrent_name
                )
            else:
            '''
            response_data = await oc_client.add_magnet_link(magnet_link)
            request_id = response_data["requestId"]

        # Wait for download completion and get the direct link
        torrent_info = await oc_client.wait_for_status(
            request_id, "downloaded", max_retries, retry_interval
        )
        login_to_oc(user_data)
        return await oc_client.create_download_link(
            request_id,
            torrent_info,
            stream,
            filename,
            season,
            episode,
            background_tasks,
        )


async def update_oc_cache_status(
    streams: List[TorrentStreams], user_data: UserData, **kwargs
):
    """Updates the cache status of streams based on OffCloud's instant availability."""
    try:
        async with OffCloud(token=user_data.streaming_provider.token) as oc_client:
            instant_availability_data = (
                await oc_client.get_torrent_instant_availability(
                    [stream.id for stream in streams]
                )
            )
            if not instant_availability_data:
                return
            for stream in streams:
                stream.cached = stream.id in instant_availability_data
    except ProviderException:
        pass


async def fetch_downloaded_info_hashes_from_oc(
    user_data: UserData, **kwargs
) -> List[str]:
    """Fetches the info_hashes of all torrents downloaded in the OffCloud account."""
    try:
        async with OffCloud(token=user_data.streaming_provider.token) as oc_client:
            available_torrents = await oc_client.get_user_torrent_list()
            return [
                torrent["originalLink"].split("btih:")[1].split("&")[0]
                for torrent in available_torrents
                if "btih:" in torrent["originalLink"]
            ]
    except ProviderException:
        return []


async def delete_all_torrents_from_oc(user_data: UserData, **kwargs):
    """Deletes all torrents from the Offcloud account."""
    async with OffCloud(token=user_data.streaming_provider.token) as oc_client:
        torrents = await oc_client.get_user_torrent_list()
        await asyncio.gather(
            *[oc_client.delete_torrent(torrent["requestId"]) for torrent in torrents],
            return_exceptions=True,
        )


async def validate_offcloud_credentials(user_data: UserData, **kwargs) -> dict:
    """Validates the OffCloud credentials."""
    try:
        async with OffCloud(token=user_data.streaming_provider.token) as oc_client:
            await oc_client.get_user_torrent_list()
            return {"status": "success"}
    except ProviderException:
        return {
            "status": "error",
            "message": "OffCloud API key is invalid or has expired",
        }


def login_to_oc(user_data: UserData):
    import os
    import logging
    if os.environ.get("OFFCLOUD_USER") is None:
        logging.info("No offcloud user to login")
        return

    import requests
    from utils.network import encode_mediaflow_proxy_url

    session = requests.Session()
    if (
            user_data.mediaflow_config
            and user_data.mediaflow_config.proxy_debrid_streams
    ):
        url = encode_mediaflow_proxy_url(
            user_data.mediaflow_config.proxy_url,
            "/proxy/endpoint",
            "https://offcloud.com/api/login",
            query_params={"api_password": user_data.mediaflow_config.api_password, "verify_ssl": "false"},
        )
    else:
        url = "https://offcloud.com/api/login"

    logging.info(f"Logging into to {url}")
    session.post(url,
                 data={'username': os.environ.get("OFFCLOUD_USER"),
                       'password': os.environ.get("OFFCLOUD_PASSWORD")})
