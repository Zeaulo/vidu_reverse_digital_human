"""仅保存在本地进程内的 OBS 播放令牌。"""
import secrets


tokens = {}  # 随机令牌映射到 Studio 会话 ID。


def current(session_id):
    """返回当前会话的有效令牌，没有则返回空值。"""
    return next((token for token, owner in tokens.items() if owner == session_id), None)


def revoke(session_id):
    """撤销指定会话的全部 OBS 播放权限。"""
    for token, owner in list(tokens.items()):
        if owner == session_id:
            del tokens[token]


def issue(session_id):
    """轮换令牌，旧链接立即失效。"""
    revoke(session_id)
    token = secrets.token_urlsafe(32)
    tokens[token] = session_id
    return token
