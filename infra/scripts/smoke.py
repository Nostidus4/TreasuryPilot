import json
import socket
import urllib.request


def require_tcp(name: str, host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=3):
        print(f"ok: {name} ({host}:{port})")


def require_http(name: str, url: str) -> None:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"{name} returned HTTP {response.status}")
        print(f"ok: {name} ({url})")


def require_anvil() -> None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}
    ).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8545",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.load(response)
    if body.get("result") != "0x7a69":
        raise RuntimeError(f"unexpected Anvil chain id: {body.get('result')}")
    print("ok: anvil (chain id 31337)")


def main() -> None:
    require_tcp("postgres", "127.0.0.1", 5432)
    require_tcp("redis", "127.0.0.1", 6379)
    require_http("minio", "http://127.0.0.1:9000/minio/health/live")
    require_anvil()
    require_http("api", "http://127.0.0.1:8000/v1/health")
    require_http("web", "http://127.0.0.1:5173/healthz")


if __name__ == "__main__":
    main()
