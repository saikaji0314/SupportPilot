"""使用 bcrypt 库散列密码；不保存或记录明文。"""
import bcrypt

# 未知账号也做密码核验，避免直接跳过耗时计算。
DUMMY_HASH = bcrypt.hashpw(b"synthetic-dummy-password", bcrypt.gensalt()).decode()


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def verify_password(password, encoded):
    valid = bcrypt.checkpw(password.encode("utf-8"), (encoded or DUMMY_HASH).encode())
    return valid and encoded is not None
