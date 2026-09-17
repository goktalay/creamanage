"""Kamera görüntüsü (sunucu tarafı): yazıcıya özel görüntü URL'sinden tek kare alır.

K2 ailesinde stok yazılım JPEG anlık görüntü ucu sunmaz; kamera yalnız WebRTC'dir
(``http://<ip>:8000/call/webrtc_local``). Bu yüzden K2'de tek kare tarayıcıda WebRTC ile
alınır (web/js). Sunucu tarafı yol, isteğe bağlı ``kamera_url`` içindir:
  * go2rtc: ``http://go2rtc:1984/api/frame.jpeg?src=yazici12``
    (go2rtc akışı: ``webrtc:http://<ip>:8000/call/webrtc_local#format=creality``)
  * K1 ailesi MJPEG: ``http://<ip>:8080/?action=snapshot``  ya da ``?action=stream`` (ilk kare)
"""
from __future__ import annotations

import aiohttp

JPEG_BAS, JPEG_SON = b"\xff\xd8", b"\xff\xd9"
EN_BUYUK = 8 * 1024 * 1024


async def goruntu_al(url: str, zaman_asimi: float = 12.0) -> tuple[bytes, str]:
    """(veri, content-type). MJPEG akışından ilk JPEG karesini ayıklar."""
    zaman = aiohttp.ClientTimeout(total=zaman_asimi, sock_connect=5)
    async with aiohttp.ClientSession(timeout=zaman) as oturum:
        async with oturum.get(url) as yanit:
            if yanit.status != 200:
                raise RuntimeError(f"HTTP {yanit.status}")
            tur = (yanit.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if tur.startswith("multipart/") or tur == "":
                tampon = b""
                async for parca in yanit.content.iter_chunked(65536):
                    tampon += parca
                    bas = tampon.find(JPEG_BAS)
                    if bas >= 0:
                        son = tampon.find(JPEG_SON, bas + 2)
                        if son >= 0:
                            return tampon[bas:son + 2], "image/jpeg"
                    if len(tampon) > EN_BUYUK:
                        break
                raise RuntimeError("akışta JPEG karesi bulunamadı")
            if not tur.startswith("image/"):
                raise RuntimeError(f"görüntü değil: {tur}")
            veri = await yanit.content.read(EN_BUYUK)
            return veri, tur
