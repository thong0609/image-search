"""Local key and first administrator provisioning; no default credentials."""

import argparse
import getpass
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from image_search.adapters.postgres.database import create_database_engine
from image_search.auth.service import AuthService
from image_search.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init-key", "create-admin"])
    parser.add_argument("--email")
    parser.add_argument("--name", default="Quản trị viên")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "init-key":
        path = settings.auth_private_key
        path.parent.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        print("Đã tạo khóa. Giữ khóa ngoài Git và sao lưu ở nơi riêng tư.")
        return
    if not args.email or "@" not in args.email:
        parser.error("Cần --email hợp lệ")
    password = getpass.getpass("Mật khẩu admin (ít nhất 12 ký tự): ")
    if len(password) < 12 or password != getpass.getpass("Nhập lại mật khẩu: "):
        parser.error("Mật khẩu chưa đủ dài hoặc không khớp")
    engine = create_database_engine(settings)
    try:
        AuthService(engine, settings).create_user(args.email, args.name, password, "admin")
        print("Đã tạo quản trị viên.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
