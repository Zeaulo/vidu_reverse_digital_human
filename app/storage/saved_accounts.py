"""使用 Windows 当前用户 DPAPI 加密保存短期账号 Cookie。"""
import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path

from app.config.settings import ROOT_DIR


class Blob(ctypes.Structure):
    """Windows DPAPI 使用的字节缓冲区。"""
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    """使用当前 Windows 登录用户加密或解密字节，不显示系统对话框。"""
    buffer = ctypes.create_string_buffer(data)  # 保持输入缓冲区在调用期间有效。
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.windll.crypt32  # 操作系统提供的 DPAPI。
    kernel = ctypes.windll.kernel32
    kernel.LocalFree.argtypes = [ctypes.c_void_p]  # 指针宽度必须与系统一致。
    kernel.LocalFree.restype = ctypes.c_void_p
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.restype = wintypes.BOOL
    if decrypt:
        ok = operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise OSError('Windows 无法处理账号加密数据')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class SavedAccounts:
    """单机用户的加密账号文件；过期记录不再提供恢复。"""

    def __init__(self, path=None, clock=time.time):
        self.path = Path(path or ROOT_DIR / 'config' / 'saved_accounts.bin')  # 不提交版本库。
        self.clock = clock

    def read(self):
        """读取并过滤 24 小时过期记录；解密失败明确报错。"""
        if not self.path.exists():
            return {}
        data = json.loads(protect(self.path.read_bytes(), decrypt=True).decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('账号文件格式错误')
        active = {phone: entry for phone, entry in data.items() if isinstance(entry, dict) and entry.get('expires', 0) > self.clock()}
        if len(active) != len(data):  # 删除过期账号的持久数据，而不只隐藏候选。
            if active:
                self.write(active)
            else:
                self.path.unlink(missing_ok=True)
        return active

    def write(self, data):
        """先写入同目录临时文件，再原子替换加密文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        try:
            temporary.write_bytes(protect(json.dumps(data, ensure_ascii=False).encode('utf-8')))
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, phone, cookies):
        """保存本次登录的 Cookie，过期时间不超过二十四小时。"""
        data = self.read()
        data[phone] = {'expires': self.clock() + 86400, 'cookies': cookies}
        self.write(data)

    def delete(self, phone=None):
        """清除指定账号或全部已保存账号。"""
        if phone is None:
            self.path.unlink(missing_ok=True)
            return
        data = self.read()
        data.pop(phone, None)
        self.write(data)
