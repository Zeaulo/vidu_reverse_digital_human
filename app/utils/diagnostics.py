"""记录不含账号、凭据或消息正文的通话诊断事件。"""
import logging
from logging.handlers import RotatingFileHandler
from app.config.settings import ROOT_DIR


logger = logging.getLogger('studio_diagnostics')  # 专属诊断日志。
if not logger.handlers:
    directory = ROOT_DIR / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / 'call_diagnostics.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def record(event, reason=None):
    """只允许写入固定事件名与白名单原因，避免泄漏上游数据。"""
    allowed = {'client_reconnect_timeout', 'sip_reconnect_timeout', 'timeout_hangup', 'prepared_timeout',
               'waiting_timeout', 'connection_lost', 'browser_closed', 'server_error', 'server_hangup',
               'init_rejected', 'user_hangup', 'media_not_ready', 'login_required', 'recovery_failed', 'duration_limit', 'audit_rejected',
               'content_policy_ended', 'policy_recovery_failed'}
    logger.info('event=%s reason=%s', event, reason if reason in allowed else ('other' if reason else 'none'))
