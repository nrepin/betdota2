"""Сетевой запрос с обходом падений прокси.

Python берёт HTTP_PROXY/HTTPS_PROXY из окружения (у нас это локальный Hiddify, 127.0.0.1:12334). Когда прокси
выключается или перезапускается, запрос падает с WinError 10061, хотя OpenDota и PARI доступны напрямую.
Поэтому сначала пробуем напрямую, затем через прокси, затем снова напрямую. Ответы сервера (HTTP 4xx/5xx)
не повторяются: их обрабатывает вызывающий код.
"""
import time
import urllib.error
import urllib.request

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_PROXIED = urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies()))


def urlopen(req, timeout=30):
    last = None
    for opener in (_DIRECT, _PROXIED, _DIRECT):
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except OSError as ex:  # URLError, обрыв, таймаут
            last = ex
            time.sleep(1)
    raise last
