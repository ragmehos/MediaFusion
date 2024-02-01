import json
import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from streaming_providers.torbox.client import Torbox
from db import schemas
from utils import crypto, const, parser

router = APIRouter()


def get_user_data(request: Request) -> schemas.UserData:
    return request.user


@router.get("/{secret_str}/status")
async def authorize(user_data: schemas.UserData = Depends(get_user_data), ):
    torbox_client = Torbox(token=user_data.streaming_provider.token)
    content = torbox_client.get_user_torrent_list()
    return_content = []
    for c in content.get("data", []):
        return_content.append({
            "name": c.get("name", ""),
            "download_finished": c.get("download_present", False),
            "eta": "0" if c.get("progress") == 1 else str(datetime.timedelta(seconds=c.get("eta"))),
            "size": parser.convert_bytes_to_readable(c.get("size")),
            "progress": c.get("progress")*100,

        })

    return JSONResponse(content=return_content,
                        headers=const.NO_CACHE_HEADERS)
