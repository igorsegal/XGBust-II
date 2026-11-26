# -*- coding: utf-8 -*-
"""Проверка связи с Dukascopy. Ничего не скачивает на диск, пишет отчёт в dukas_test.txt."""
import datetime as dt
import http.client
import pathlib
import shutil
import socket
import ssl
import subprocess
import time
import urllib.request

HOST = "datafeed.dukascopy.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "dukas_test.txt"


def say(line):
    print(line, flush=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def path(hour):
    return f"/datafeed/EURUSD/2020/00/02/{hour:02d}h_ticks.bi5"


def timed(label, action):
    start = time.time()
    try:
        result = action()
        say(f"{label}: OK {result} за {time.time() - start:.1f} с")
    except Exception as e:
        say(f"{label}: ОШИБКА {type(e).__name__}: {e} за {time.time() - start:.1f} с")


def main():
    OUT.unlink(missing_ok=True)
    say(f"Проверка {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"Прокси Windows: {urllib.request.getproxies() or 'нет'}")

    addresses = []
    try:
        for family, _, _, _, addr in socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM):
            if (family, addr[0]) not in addresses:
                addresses.append((family, addr[0]))
    except OSError as e:
        say(f"Адрес сервера не определяется: {e}")
    say(f"Адресов сервера: {len(addresses)}")

    def connect(family, ip):
        context = ssl.create_default_context()
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(30)
            s.connect((ip, 443))
            with context.wrap_socket(s, server_hostname=HOST) as t:
                return t.version()

    for family, ip in addresses[:4]:
        kind = "IPv6" if family == socket.AF_INET6 else "IPv4"
        for attempt in (1, 2):
            timed(f"1. {kind} {ip} попытка {attempt}", lambda: connect(family, ip))

    def by_urllib(hour):
        req = urllib.request.Request(f"https://{HOST}{path(hour)}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            return f"{len(r.read())} байт"

    for hour in (8, 9):
        timed(f"2. как в программе, час {hour}", lambda: by_urllib(hour))

    keep = http.client.HTTPSConnection(HOST, timeout=60)

    def by_keep(hour):
        try:
            keep.request("GET", path(hour), headers=HEADERS)
            r = keep.getresponse()
            return f"код {r.status}, {len(r.read())} байт"
        except Exception:
            keep.close()
            raise

    for hour in range(8, 16):
        timed(f"3. одно соединение, час {hour}", lambda: by_keep(hour))
    keep.close()

    curl = shutil.which("curl")
    if not curl:
        say("4. curl не найден")
    else:
        command = [curl, "-s", "--connect-timeout", "30", "--max-time", "60",
                   "-w", "код %{http_code}, адрес %{remote_ip}, соединение %{time_connect} с, всего %{time_total} с\n"]
        for hour in (8, 9, 10):
            command += ["-o", "NUL", f"https://{HOST}{path(hour)}"]
        try:
            r = subprocess.run(command, capture_output=True, text=True, timeout=200)
            say(f"4. curl (код выхода {r.returncode}):\n{r.stdout.strip()}")
        except Exception as e:
            say(f"4. curl: ОШИБКА {e}")
    say("TEST DONE")


if __name__ == "__main__":
    main()
