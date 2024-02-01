import logging
import re
from typing import Any

import PTT

from thefuzz import fuzz

import utils.validation_helper
from db.models import TorrentStreams
from db.schemas import UserData
from streaming_providers.exceptions import ProviderException
from streaming_providers.torbox.client import Torbox
from utils.validation_helper import is_video_file, get_season_and_episode


def get_video_url_from_torbox(
    info_hash: str,
    magnet_link: str,
    user_data: UserData,
    filename: str,
    season: int = None,
    episode: int = None,
    **kwargs,
) -> str:
    torbox_client = Torbox(token=user_data.streaming_provider.token)

    # Check if the torrent already exists
    torrent_info = torbox_client.get_available_torrent(info_hash)
    if torrent_info:
        if (
            torrent_info["download_finished"] is True
            and torrent_info["download_present"] is True
        ):
            file_id = select_file_id_from_torrent(torrent_info, filename, season, episode)
            response = torbox_client.create_download_link(
                torrent_info.get("id"),
                file_id,
            )
            return response["data"]
    else:
        # If torrent doesn't exist, add it
        response = torbox_client.add_magnet_link(magnet_link)
        # Response detail has "Found Cached Torrent. Using Cached Torrent." if it's a cached torrent,
        # create download link from it directly in the same call.
        if "Found Cached" in response.get("detail"):
            torrent_info = torbox_client.get_available_torrent(info_hash)
            if torrent_info:
                file_id = select_file_id_from_torrent(torrent_info, filename, season, episode)
                response = torbox_client.create_download_link(
                    torrent_info.get("id"),
                    file_id,
                )
                return response["data"]

    raise ProviderException(
        f"Torrent did not reach downloaded status.",
        "torrent_not_downloaded.mp4",
    )



# Yield successive n-sized
# chunks from l.
def divide_chunks(l, n):
    # looping till length l
    for i in range(0, len(l), n):
        yield l[i:i + n]


def update_torbox_cache_status(
    streams: list[TorrentStreams], user_data: UserData, **kwargs
):
    """Updates the cache status of streams based on Torbox's instant availability."""

    # Torbox allows only 100 torrents to be passed for cache status, send 40 at a time.
    streams_divided_list = list(divide_chunks(streams, 80))
    for streams_list in streams_divided_list:
        try:
            torbox_client = Torbox(token=user_data.streaming_provider.token)
            instant_availability_data = torbox_client.get_torrent_instant_availability(
                [stream.id for stream in streams_list]
            ) or []
            for stream in streams_list:
                stream.cached = bool(stream.id in instant_availability_data)
        except ProviderException as e:
            logging.error(f"Failed to get cached status from torbox {e}")
            pass


def fetch_downloaded_info_hashes_from_torbox(
    user_data: UserData, **kwargs
) -> list[str]:
    """Fetches the info_hashes of all torrents downloaded in the Torbox account."""
    try:
        torbox_client = Torbox(token=user_data.streaming_provider.token)
        available_torrents = torbox_client.get_user_torrent_list()
        if not available_torrents.get("data"):
            return []
        return [torrent["hash"] for torrent in available_torrents["data"]]

    except ProviderException:
        return []


def select_file_id_from_torrent(
    torrent_info: dict[str, Any], filename: str, season: int, episode: int
) -> int:
    """Select the file id from the torrent info."""
    files = torrent_info["files"]
    '''
    exact_match = next((f for f in files if filename in f["name"]), None)
    if exact_match:
        return exact_match["id"]

    # Fuzzy matching as a fallback
    for file in files:
        file["fuzzy_ratio"] = fuzz.ratio(filename, file["name"])
    selected_file = max(files, key=lambda x: x["fuzzy_ratio"])

    # If the fuzzy ratio is less than 50, then select the largest file
    if selected_file["fuzzy_ratio"] < 50:
        selected_file = max(files, key=lambda x: x["size"])

    if episode:
        # Select the file with the matching episode number
        for file in files:
            if episode in PTT.parse_title(file["name"]).get("episodes", []):
                return file["id"]

    if "video" not in selected_file["mime_type"]:
        raise ProviderException(
            "No matching file available for this torrent", "no_matching_file.mp4"
        )

    return selected_file["id"]
    '''
    possible_links = []
    for index, file in enumerate(files):
        if filename is None or filename == "":
            if is_video_file(file["name"]):
                possible_links.append(file)
        else:
            parsed_season, parsed_episode = get_season_and_episode(file["name"].split("/")[-1])
            if (is_video_file(file["name"]) and
                season in parsed_season and
                episode in parsed_episode):
                    #re.search(filename, file["name"], re.IGNORECASE)):
                possible_links.append(file)

    if len(possible_links) > 1:
        selected = max(possible_links, key=lambda x: x["size"])
        return selected["id"]
    elif len(possible_links) == 1:
        return possible_links[0]["id"]

    raise ProviderException(
        "No matching file available for this torrent", "no_matching_file.mp4"
    )


def delete_all_torrents_from_torbox(user_data: UserData, **kwargs):
    """Deletes all torrents from the Torbox account."""
    torbox_client = Torbox(token=user_data.streaming_provider.token)
    torrents = torbox_client.get_user_torrent_list().get("data")
    if not torrents:
        return
    for torrent in torrents:
        torbox_client.delete_torrent(torrent.get("id"))
