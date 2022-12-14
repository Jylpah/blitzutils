## -----------------------------------------------------------
#### Class WoTinspector 
# 
# replays.wotinspector.com
## -----------------------------------------------------------

from typing import Optional, Union, cast
import logging, json, re, sys, urllib
from aiohttp import ClientResponse
from asyncio import sleep
from bs4 import BeautifulSoup                                           # type: ignore
from pydantic import BaseModel
from pyutils.throttledclientsession import ThrottledClientSession     # type: ignore
from pyutils.utils import get_url, get_url_JSON, get_url_JSON_model   # type: ignore  
from .models import WoTBlitzReplayJSON
from hashlib import md5
from urllib.parse import urlencode, quote
from base64 import b64encode


# Setup logging
logger	= logging.getLogger()
error 	= logger.error
message	= logger.warning
verbose	= logger.info
debug	= logger.debug

SLEEP : float = 1
class WoTinspector:
    URL_WI          : str = 'https://replays.wotinspector.com'
    URL_REPLAY_LIST : str = URL_WI + '/en/sort/ut/page/'
    URL_REPLAY_DL   : str = URL_WI + '/en/download/'  
    URL_REPLAY_VIEW : str = URL_WI +'/en/view/'
    URL_REPLAY_UL   : str = 'https://api.wotinspector.com/replay/upload?'
    URL_REPLAY_INFO : str = 'https://api.wotinspector.com/replay/upload?details=full&key='
    URL_TANK_DB     : str = "https://wotinspector.com/static/armorinspector/tank_db_blitz.js"

    MAX_RETRIES     : int = 3
    REPLAY_N = 1
    DEFAULT_RATE_LIMIT = 20/3600  # 20 requests / hour

    def __init__(self, rate_limit: float = DEFAULT_RATE_LIMIT, auth_token: Optional[str] = None):

        headers : Optional[dict[str, str]] = None
        if auth_token is not None:
            headers = dict()
            headers['Authorization'] = f'Token {auth_token}'

        self.session = ThrottledClientSession(rate_limit=rate_limit, filters=[self.URL_REPLAY_INFO, self.URL_REPLAY_DL, self.URL_REPLAY_LIST], 
                                                re_filter=False, limit_filtered=True, headers = headers)


    async def close(self) -> None:
        if self.session is not None:
            debug('Closing aiohttp session')
            await self.session.close()
       

    def get_url_replay_JSON(self, id: str) -> str:
        return f'{self.URL_REPLAY_INFO}{id}'


    async def get_replay(self, replay_id: str) -> WoTBlitzReplayJSON | None:
        try:
            replay : BaseModel | None = await get_url_JSON_model(self.session, self.get_url_replay_JSON(replay_id), resp_model=WoTBlitzReplayJSON)
            if replay is None: 
                return None
            else:
                return cast(WoTBlitzReplayJSON, replay)
        except Exception as err:
            error(f'Unexpected Exception: {err}') 
        return None


    async def post_replay(self, data, filename = 'Replay', account_id = 0, title = 'Replay', 
                            priv = False, N = None) -> WoTBlitzReplayJSON | None:
        try:
            N = N if N is not None else self.REPLAY_N
            self.REPLAY_N += 1

            hash = md5()
            hash.update(data)
            replay_id = hash.hexdigest()

            ##  Testing if the replay has already been posted
            json_resp : WoTBlitzReplayJSON | None = await self.get_replay(replay_id)
            if json_resp is not None:
                debug(f'{N}: Already uploaded: {title}')
                return json_resp

            params = {
                'title'			: title,
                'private' 		: (1 if priv else 0),
                'uploaded_by'	: account_id,
                'details'		: 'full',
                'key'           : replay_id
            } 

            url = self.URL_REPLAY_UL + urlencode(params, quote_via=quote)
            #debug('URL: ' + url)
            headers ={'Content-type':  'application/x-www-form-urlencoded'}
            payload = { 'file' : (filename, b64encode(data)) }
        except Exception as err:
            error(f'Treahd {N}: Unexpected Exception: {err}')
            return None

        replay : WoTBlitzReplayJSON | None = None
        for retry in range(self.MAX_RETRIES):
            debug(f'Thread {id}: Posting: {title} Try #: {retry + 1}/{self.MAX_RETRIES}')
            try:
                async with self.session.post(url, headers=headers, data=payload) as resp:
                    debug(f'{N}: HTTP response: {resp.status}')
                    if resp.status == 200:								
                        debug(f'{N}: HTTP POST 200 = Success. Reading response data')                        
                        replay = WoTBlitzReplayJSON.from_str(await resp.text())
                        if replay is not None:
                            debug(f'{N}: Response data read. Status OK') 
                            return replay	
                        debug(f'{N}: title : Receive invalid JSON')
                    else:
                        debug(f'{N}: Got HTTP/{resp.status}')
            except Exception as err:
                debug(f'{N}: Unexpected exception {err}')
            await sleep(SLEEP)
            
        debug(f'{N}: Could not post replay: {title}')
        return replay


    async def get_replay_listing(self, page: int = 0) -> ClientResponse:
        url : str = self.get_url_replay_listing(page)
        return cast(ClientResponse, await self.session.get(url))        # mypy checks fail with aiohttp _request() return type...


    @classmethod
    def get_url_replay_listing(cls, page : int) -> str:
        return f'{cls.URL_REPLAY_LIST}{page}?vt=#filters'


    @classmethod
    def get_url_replay_view(cls, replay_id):
        return cls.URL_REPLAY_VIEW + replay_id


    @classmethod
    def parse_replay_ids(cls, doc: str) -> set[str]:
        """Get replay ids links from WoTinspector.com replay listing page"""
        replay_ids : set[str] = set()
        try:
            soup = BeautifulSoup(doc, 'lxml')
            links = soup.find_all('a')
            
            for tag in links:
                link = tag.get('href',None)
                id : str | None = cls.get_replay_id(link)
                if id is not None:
                    replay_ids.add(id)
                    debug('Adding replay link:' + link)
        except Exception as err:
            error(f'Failed to parse replay links {err}')
        return replay_ids
    

    @classmethod
    def get_replay_id(cls, url: str) -> str | None:
        if (url is not None) and url.startswith(cls.URL_REPLAY_DL):
            return url.rsplit('/', 1)[-1]
        else: 
            return None
