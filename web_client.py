"""HTTP-only frontend adapter. No database access, retries or shared credentials."""
import os
import httpx


class ApiError(Exception):
    def __init__(self, message, status=0, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def request_api(method, path, *, token=None, data=None):
    base = os.getenv("CAREER_API_URL", "http://127.0.0.1:8000").rstrip("/")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=httpx.Timeout(180.0, connect=5.0), trust_env=False) as client:
            response = client.request(method, base + path, headers=headers, json=data)
    except httpx.TimeoutException:
        raise ApiError("等待结果超时。任务可能仍在处理，请先核对结果，不要立即重复提交。") from None
    except httpx.RequestError:
        raise ApiError("无法连接服务，请确认后端已启动。") from None
    try:
        payload = response.json()
    except ValueError:
        raise ApiError("服务返回了无法识别的结果，请稍后再试。", response.status_code) from None
    if not isinstance(payload, dict):
        raise ApiError("服务返回格式异常。", response.status_code)
    if response.is_error:
        if response.status_code == 401:
            message = "登录失败，请检查邮箱和密码。" if path == "/auth/login" else "登录已过期，请重新登录。"
        else:
            detail = payload.get("detail")
            if isinstance(detail, str):
                message = detail
            elif isinstance(detail, dict):
                message = detail.get("message", "请求未完成，请检查输入后重试。")
            elif payload.get("errors"):
                message = payload["errors"][-1].get("message", "任务未完成。")
            elif response.status_code == 422:
                message = "填写内容不符合要求，请检查必填项。"
            else:
                message = "服务暂时不可用，请稍后重试。"
        raise ApiError(message, response.status_code, payload)
    return payload
