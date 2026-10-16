import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from dotenv import load_dotenv

from database import get_db_connection


# =========================
# 1. 加载环境变量
# =========================

load_dotenv()


JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY"
)

if not JWT_SECRET_KEY:
    raise ValueError(
        "没有读取到 JWT_SECRET_KEY，请检查 .env 文件"
    )


JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


# =========================
# 2. 用户注册
# =========================

def register_user(
    name: str,
    email: str,
    password: str
):

    # -------------------------
    # 基础输入校验
    # -------------------------

    name = name.strip()
    email = email.strip().lower()

    if not name:
        return {
            "error": "用户名不能为空"
        }

    if not email:
        return {
            "error": "邮箱不能为空"
        }

    if len(password.encode("utf-8")) > 72:
        return {"error": "密码 UTF-8 编码长度不能超过 72 字节"}

    if len(password) < 6:
        return {
            "error": "密码至少需要 6 位"
        }


    # -------------------------
    # 连接数据库
    # -------------------------

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        # =========================
        # 检查邮箱是否已经注册
        # =========================

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE email = %s
            """,
            (email,)
        )

        existing_user = (
            cursor.fetchone()
        )


        if existing_user:
            return {
                "error": "该邮箱已经注册"
            }


        # =========================
        # 密码哈希
        # =========================

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")


        # =========================
        # 写入 MySQL
        # =========================

        cursor.execute(
            """
            INSERT INTO users (
                name,
                email,
                password_hash
            )
            VALUES (%s, %s, %s)
            """,
            (
                name,
                email,
                password_hash
            )
        )


        connection.commit()

        user_id = cursor.lastrowid


        return {
            "id": user_id,
            "name": name,
            "email": email,
            "message": "注册成功"
        }


    finally:

        cursor.close()
        connection.close()


# =========================
# 3. 创建 JWT
# =========================

def create_access_token(
    user_id: int,
    email: str
):

    expire_time = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            hours=JWT_EXPIRE_HOURS
        )
    )


    payload = {

        # JWT 标准 subject
        "sub": str(user_id),

        # 项目中方便直接使用
        "user_id": user_id,

        "email": email,

        "exp": expire_time
    }


    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )


    return token


# =========================
# 4. 用户登录
# =========================

def login_user(
    email: str,
    password: str
):

    email = email.strip().lower()


    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        # =========================
        # 查询用户
        # =========================

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash
            FROM users
            WHERE email = %s
            """,
            (email,)
        )


        user = cursor.fetchone()


    finally:

        cursor.close()
        connection.close()


    # =========================
    # 用户不存在
    # =========================

    if not user:

        return {
            "error": "邮箱或密码错误"
        }


    # =========================
    # 验证密码
    # =========================

    if len(password.encode("utf-8")) > 72:
        return {"error": "邮箱或密码错误"}

    password_ok = bcrypt.checkpw(
        password.encode("utf-8"),
        user[
            "password_hash"
        ].encode("utf-8")
    )


    if not password_ok:

        return {
            "error": "邮箱或密码错误"
        }


    # =========================
    # 创建 JWT
    # =========================

    access_token = (
        create_access_token(
            user_id=user["id"],
            email=user["email"]
        )
    )


    return {
        "access_token":
            access_token,

        "token_type":
            "bearer",

        "user_id":
            user["id"],

        "name":
            user["name"],

        "email":
            user["email"]
    }


# =========================
# 5. 解析 JWT
# =========================

def decode_access_token(
    token: str
):

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[
                JWT_ALGORITHM
            ]
        )


        return payload


    except jwt.ExpiredSignatureError:

        return {
            "error":
                "登录已过期，请重新登录"
        }


    except jwt.InvalidTokenError:

        return {
            "error":
                "无效的登录凭证"
        }


# =========================
# 6. 根据 JWT 获取当前用户
# =========================

def get_user_from_token(
    token: str
):

    # -------------------------
    # 先解析 JWT
    # -------------------------

    payload = decode_access_token(
        token
    )


    if "error" in payload:
        return payload


    user_id = payload.get(
        "user_id"
    )


    if not user_id:

        return {
            "error":
                "登录凭证中缺少用户信息"
        }


    # -------------------------
    # 再去 MySQL 确认用户存在
    # -------------------------

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )


        user = cursor.fetchone()


    finally:

        cursor.close()
        connection.close()


    if not user:

        return {
            "error":
                "用户不存在"
        }


    return {
        "id":
            user["id"],

        "name":
            user["name"],

        "email":
            user["email"],

        "created_at":
            user["created_at"]
    }