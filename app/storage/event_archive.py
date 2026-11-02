"""单次直播连接的临时事件归档，用于完整导出。"""
import json
import sqlite3
from threading import RLock


class EventArchive:
    """使用 SQLite 临时文件保存完整记录，关闭连接后自动释放。"""

    def __init__(self):
        """创建当前会话专属临时数据库。"""
        self.lock = RLock()  # 多线程关闭或读取时串行访问连接。
        self.database = sqlite3.connect('', isolation_level=None, check_same_thread=False)  # SQLite 管理的临时磁盘文件。
        self.database.execute('CREATE TABLE events (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL)')

    def clear(self):
        """开始新连接时清除上一轮记录。"""
        with self.lock:
            self.database.execute('DELETE FROM events')

    def add(self, record):
        """写入一个事件并返回归档内部序号。"""
        with self.lock:
            cursor = self.database.execute('INSERT INTO events (payload) VALUES (?)',
                                           (json.dumps(record, ensure_ascii=False),))
            return cursor.lastrowid

    def update(self, sequence, record):
        """同步事件的最终调度状态。"""
        with self.lock:
            self.database.execute('UPDATE events SET payload = ? WHERE sequence = ?',
                                  (json.dumps(record, ensure_ascii=False), sequence))

    def all(self):
        """按收到顺序读取本次连接的完整记录。"""
        with self.lock:
            return [json.loads(row[0]) for row in self.database.execute('SELECT payload FROM events ORDER BY sequence')]

    def close(self):
        """销毁临时归档及其数据库资源。"""
        with self.lock:
            if self.database is not None:  # 重复关闭不会引发异常。
                self.database.close()
                self.database = None
