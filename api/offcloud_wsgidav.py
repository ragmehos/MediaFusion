import os
import urllib
import datetime
from functools import cached_property

from urllib.parse import quote

import requests
import wsgidav.wsgidav_app as wsgidav_app
from wsgidav import util
from wsgidav.dav_provider import DAVProvider, DAVNonCollection
from wsgidav.dav_provider import DAVCollection
from wsgidav.dav_error import DAVError, HTTP_FORBIDDEN, HTTP_NOT_FOUND

from api.SeekableHTTPFile import SeekableHTTPFile
from streaming_providers.offcloud.client import OffCloud

import urllib3
pm = urllib3.PoolManager(num_pools=200)

_logger = util.get_module_logger(__name__)
offcloud_data = []


class OffcloudProvider(DAVProvider):
    def __init__(self, oc):
        super().__init__()
        self.oc = oc
        self.refreshed_time = datetime.datetime.now() - datetime.timedelta(hours=48)
        # Create a cache of file size for faster retrieval
        if os.environ.get("OFFCLOUD_USER") is None:
            return
        self.get_offcloud_data()

    def get_offcloud_data(self):
        if datetime.datetime.now() - self.refreshed_time <= datetime.timedelta(hours=1):
            return
        session = requests.Session()
        session.post("https://offcloud.com/api/login",
                     data={'username': os.environ.get("OFFCLOUD_USER"),
                           'password': os.environ.get("OFFCLOUD_PASSWORD")})
        i = 0
        while True:
            resp = session.post('https://offcloud.com/cloud/history', data={'page': i}).json()
            offcloud_data.extend(resp['history'])
            i = i + 1
            if resp['isEnd'] is True:
                self.refreshed_time = datetime.datetime.now()
                break

    def get_resource_inst(self, path, environ):
        try:
            _logger.info("get_resource_inst('%s')" % path)
            if os.environ.get("OFFCLOUD_USER") is None:
                return
            self.get_offcloud_data()
            root = OffcloudCollection(environ, path, self.oc)
            return root.resolve(environ["SCRIPT_NAME"], path)
        except DAVError as e:
            raise e
        except Exception as e:
            print("Error:", e)
            raise DAVError(HTTP_NOT_FOUND)

    def is_readonly(self):
        return True


class OffcloudCollection(DAVCollection):
    def __init__(self, environ, path, oc):
        super().__init__(path, environ)
        self.oc = oc
        self.list = self.oc.get_user_torrent_list()

    def get_display_info(self):
        return {"type": "Directory"}

    def get_member(self, name):
        try:
            r = None
            for l in self.list:
                if l.get("fileName") == name:
                    r = l
            if r is None:
                return
            if r.get("isDirectory") is False:
                return OffcloudFile(self.environ, f"/{r.get('fileName')}",
                                    f"https://{r.get('server')}.offcloud.com/cloud/download/{r.get('requestId')}/{r.get('fileName')}")
            else:
                return OffcloudDirectory(self.environ, f"/{r.get('fileName')}", self.oc, r.get("requestId"), r)
        except Exception as e:
            print("Error:", e)
            raise DAVError(HTTP_FORBIDDEN)

    def create_collection(self, name):
        # Not implemented for simplicity
        raise DAVError(HTTP_FORBIDDEN)

    def get_member_names(self):
        response = self.list
        parsed = []
        for r in response:
            if r.get("status") == "downloaded":
                parsed.append(r.get("fileName"))
        return parsed


class OffcloudDirectory(DAVCollection):
    def __init__(self, environ, path, oc, request_id, r):
        super().__init__(path, environ)
        self.oc = oc
        self.request_id = request_id
        self.r = r

    @cached_property
    def folder_links(self):
        return self.oc.explore_folder_links(self.request_id)

    @cached_property
    def processed_folder_links(self):
        d = {}
        for l in self.folder_links:
            d[l.split("/")[-1]] = l
        return d

    def get_display_info(self):
        return {"type": "Directory"}

    def get_member(self, name):
        try:
            return OffcloudFile(self.environ, f"{self.path}/{name}", self.processed_folder_links.get(name))
        except Exception as e:
            print("Error:", e)
            raise DAVError(HTTP_FORBIDDEN)

    def create_collection(self, name):
        # Not implemented for simplicity
        raise DAVError(HTTP_FORBIDDEN)

    def get_member_names(self):
        return list(self.processed_folder_links.keys())


class OffcloudFile(DAVNonCollection):
    def __init__(self, environ, path, file_info):
        super().__init__(path, environ)
        self.file_info = urllib.parse.quote(file_info, safe=':/~()*!.\'')

    @cached_property
    def file_headers(self):
        return pm.request("HEAD", self.file_info).info()

    def get_content_length(self):
        '''
        episode = PTN.parse(self.file_info).get("episode")
        if episode == None:
            for d in offcloud_data:
                if d["fileName"] == self.path.split("/")[1]:
                    print(f"CACHED VALUE for {d['fileName']} size {d['fileSize']}")
                    return int(d["fileSize"])
        print(f"UNCACHED VALUE or episode {episode}")
        '''
        return int(self.file_headers.get('Content-Length', 0))

    # Let the default implementation guess the mime type from the URL
    #def get_content_type(self):
    #    return self.file_headers.get('Content-Type', "")

    def get_content(self):
        # Try to login to get the latest ip registered
        session = requests.Session()
        session.post("https://offcloud.com/api/login", data={'username': os.environ.get("OFFCLOUD_USER"),
                                                             'password': os.environ.get("OFFCLOUD_PASSWORD")})
        return SeekableHTTPFile(self.file_info)
        #return pm.request("GET", self.file_info, preload_content=False)
        #return pm.urlopen("GET", self.file_info)

    def support_ranges(self):
        return True

    def support_etag(self):
        return True

    def get_etag(self):
        etag = self.file_headers.get('ETag', "").replace('"', '')
        if etag == '' or etag == "\'\'":
            return None


def setup_wsgi():
    oc = OffCloud(token=os.environ.get("OFFCLOUD_API_KEY"))
    # Set up Debrid provider
    debrid_provider = OffcloudProvider(oc)

    # Set up WsgiDAV with custom provider
    config = {
        "provider_mapping": {"/": debrid_provider},
        "server": "uvicorn",
        "mount_path": "/webdav",
        "verbose": 1,
        "logging.enable_loggers": [],
        "property_manager": True,
        "block_size": 8388608,
        "http_authenticator": {
            "domain_controller": None,
            "accept_basic": True,
            "accept_digest": True,
            "default_to_digest": False,
            "trusted_auth_header": None
        },
        "simple_dc": {
            "user_mapping": {
                "*": {
                    os.environ.get("WEBDAV_USER"): {
                        "password": os.environ.get("WEBDAV_PASSWORD")
                    }
                },
            }
        },
    }
    wsgidavapp = wsgidav_app.WsgiDAVApp(config)
    return wsgidavapp
