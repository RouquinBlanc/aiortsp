"""
Simple recording example from RTSP
"""

import asyncio
import contextlib
import logging

from aiortsp.rtsp.connection import RTSPConnection
from aiortsp.rtsp.record import Recorder
from aiortsp.rtsp.session import RTSPMediaSession
from aiortsp.transport import transport_for_scheme

logger = logging.getLogger("rtsp_client")
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")


async def main():
    import argparse
    from urllib.parse import urlparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--logging", type=int, default=20, help="RTSP url")
    parser.add_argument("-t", "--timeout", type=int, default=10, help="UDP timeout")
    parser.add_argument("src_url", help="RTSP source url")
    parser.add_argument("dst_url", help="RTSP destination url")
    args = parser.parse_args()

    logger.setLevel(args.logging)

    async with contextlib.AsyncExitStack() as stack:

        # Setup source connection
        src_url = urlparse(args.src_url)
        src_conn = await stack.enter_async_context(
            RTSPConnection(src_url.hostname, src_url.port or 554, src_url.username, src_url.password, logger=logger)
        )
        logger.info("SRC connected")

        # Detects if UDP or TCP must be used for RTP transport
        src_transport = await stack.enter_async_context(
            transport_for_scheme(src_url.scheme)(src_conn, logger=logger, timeout=args.timeout)
        )

        src_sess = await stack.enter_async_context(
            RTSPMediaSession(src_conn, args.src_url, src_transport, logger=logger)
        )

        # Setup destination connection
        dst_url = urlparse(args.dst_url)
        dst_conn = await stack.enter_async_context(
            RTSPConnection(dst_url.hostname, dst_url.port or 554, dst_url.username, dst_url.password, logger=logger)
        )
        logger.info("DST connected")

        # Detects if UDP or TCP must be used for RTP transport
        dst_transport = await stack.enter_async_context(
            transport_for_scheme(dst_url.scheme)(dst_conn, logger=logger, timeout=args.timeout)
        )
        dst_transport._rtcp_loop = False  # hack: do not trigger RTCP loop

        recorder = await stack.enter_async_context(
            Recorder(src_sess, dst_conn, args.dst_url, dst_transport, logger=logger)
        )

        src_transport.subscribe(recorder)

        await recorder.record()

        try:
            while src_conn.running and src_transport.running:
                await asyncio.sleep(src_sess.session_keepalive)
                await src_sess.keep_alive()

                # logger.info("received %s RTP, %s RTCP", fwd.rtp_count, fwd.rtcp_count)

        except asyncio.CancelledError:
            logger.info("stopping stream...")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
