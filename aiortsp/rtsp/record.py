"""
RTSP Media Session setup and control
"""
import asyncio
import logging
from aiortsp.transport import RTPTransport, RTPTransportClient

from .session import RTSPMediaSession, BaseSession
from aiortsp.rtp import RTP
from aiortsp.rtcp import RTCP

default_logger = logging.getLogger(__name__)


class Recorder(RTPTransportClient, BaseSession):
    """
    RTSP Recorder
    TODO Refactor to support multiple medias
    """

    def __init__(
        self,
        session: RTSPMediaSession,
        connection,
        media_url,
        transport: RTPTransport,
        media_type="video",
        logger=None,
    ):
        self.session = session

        BaseSession.__init__(self, connection, media_url, transport, media_type, logger)

    async def __aenter__(self):
        """
        At entrance of env, we expect the stream to be ready for playback
        """
        await self.announce_and_setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_val and exc_type != asyncio.CancelledError:
            self.logger.error("exception during session: %s %s", exc_type, exc_val)
        await self.teardown()

    def handle_rtp(self, rtp: RTP):
        """Handle an incoming RTP packet"""
        self.transport.send_rtp(rtp)

    def handle_rtcp(self, rtcp: RTCP):
        """Handle an incoming RTP packet"""
        self.transport.send_rtcp_report(rtcp)

    def build_sdp(self) -> bytes:
        sdp = "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=Stream\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\n"

        for media in self.session.sdp.content["media"]:
            if media["type"] != self.media_type:
                continue

            break
        else:
            raise Exception(f"no {self.media_type} found")

        sdp += f"m={media['type']} {media['port']} {media['protocol']} {media['payloads']}\r\n"
        rtp = media['rtp'][0]
        sdp += f"a=rtpmap:{rtp['payload']} {rtp['codec']}/{rtp['rate']}\r\n"
        fmtp = media["fmtp"][0]
        sdp += f"a=fmtp:{fmtp['payload']} {fmtp['config']}\r\n"
        sdp += f"a=control:streamid=0\r\n"

        return sdp.encode()

    async def announce_and_setup(self):
        """
        Perform ANNOUNCE, then SETUP
        """
        # Get supported options
        resp = await self._send("OPTIONS", url=self.media_url)
        self.save_options(resp)

        if "ANNOUNCE" not in self.session_options:
            raise RuntimeError("cannot record on URL %s: does not support ANNOUNCE", self.media_url)

        # Get SDP
        await self._send("ANNOUNCE", headers={"Content-Type": "application/sdp"}, body=self.build_sdp())

        setup_url = f"{self.media_url}/streamid=0"

        # --- SETUP <url> RTSP/1.0 ---
        headers = {}
        self.transport.on_transport_request(headers)
        headers["Transport"] += ";mode=record"
        resp = await self.connection.send_request(
            "SETUP", url=setup_url, headers=headers
        )
        self.transport.on_transport_response(resp.headers)
        self.logger.info("stream correctly setup: %s", resp)

        # Store session ID
        self.save_session(resp)

    async def record(self):
        """
        Send a PLAY request
        """

        self.logger.info("start recording %s", self.media_url)

        await self.session.play()

        resp = await self._send("RECORD", headers={"Range": "npt=now-"})
        self.logger.debug("response to record: %s", resp)
        return resp
