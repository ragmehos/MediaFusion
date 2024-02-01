from db.models import TorrentStreams
from db.schemas import UserData
from streaming_providers.exceptions import ProviderException
from streaming_providers.offcloud.client import OffCloud


def get_video_url_from_offcloud(
    info_hash: str,
    magnet_link: str,
    user_data: UserData,
    filename: str,
    max_retries=5,
    retry_interval=5,
    season: int = None,
    episode: int = None,
    **kwargs,
) -> str:
    oc_client = OffCloud(token=user_data.streaming_provider.token)

    # Check if the torrent already exists
    torrent_info = oc_client.get_available_torrent(info_hash)
    if torrent_info:
        request_id = torrent_info.get("requestId")
        torrent_info = oc_client.get_torrent_info(request_id)
        if torrent_info["status"] == "downloaded":
            login_to_oc(user_data)
            return oc_client.create_download_link(
                request_id, torrent_info, filename, season, episode
            )
        if torrent_info["status"] == "error":
            raise ProviderException(
                f"Error transferring magnet link to OffCloud. {torrent_info['errorMessage']}",
                "transfer_error.mp4",
            )
    else:
        # If torrent doesn't exist, add it
        response_data = oc_client.add_magnet_link(magnet_link)
        request_id = response_data["requestId"]

    # Wait for download completion and get the direct link
    torrent_info = oc_client.wait_for_status(
        request_id, "downloaded", max_retries, retry_interval
    )
    login_to_oc(user_data)
    return oc_client.create_download_link(request_id, torrent_info, filename, season, episode)


def update_oc_cache_status(
    streams: list[TorrentStreams], user_data: UserData, **kwargs
):
    """Updates the cache status of streams based on OffCloud's instant availability."""

    try:
        oc_client = OffCloud(token=user_data.streaming_provider.token)
        instant_availability_data = oc_client.get_torrent_instant_availability(
            [stream.id for stream in streams]
        )
        for stream in streams:
            stream.cached = any(
                torrent == stream.id for torrent in instant_availability_data
            )

    except ProviderException:
        pass


def fetch_downloaded_info_hashes_from_oc(user_data: UserData, **kwargs) -> list[str]:
    """Fetches the info_hashes of all torrents downloaded in the OffCloud account."""
    try:
        oc_client = OffCloud(token=user_data.streaming_provider.token)
        available_torrents = oc_client.get_user_torrent_list()
        magnet_links = [torrent["originalLink"] for torrent in available_torrents]
        return [
            magnet_link.split("btih:")[1].split("&")[0] for magnet_link in magnet_links
        ]

    except ProviderException:
        return []


def delete_all_torrents_from_oc(user_data: UserData, **kwargs):
    """Deletes all torrents from the Offcloud account."""
    oc_client = OffCloud(token=user_data.streaming_provider.token)
    torrents = oc_client.get_user_torrent_list()
    for torrent in torrents:
        oc_client.delete_torrent(torrent.get("requestId"))


def login_to_oc(user_data: UserData):
    import os
    if os.environ.get("OFFCLOUD_USER") is None:
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
            query_params={"api_password": user_data.mediaflow_config.api_password},
        )
    else:
        url = "https://offcloud.com/api/login"

    session.post(url,
                 data={'username': os.environ.get("OFFCLOUD_USER"),
                       'password': os.environ.get("OFFCLOUD_PASSWORD")})
