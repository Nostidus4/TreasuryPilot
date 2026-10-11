import os

from minio import Minio


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def main() -> None:
    bucket = required_environment("MINIO_BUCKET")
    client = Minio(
        "minio:9000",
        access_key=required_environment("MINIO_ROOT_USER"),
        secret_key=required_environment("MINIO_ROOT_PASSWORD"),
        secure=False,
    )
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"created private bucket: {bucket}")
    else:
        print(f"private bucket already exists: {bucket}")


if __name__ == "__main__":
    main()
