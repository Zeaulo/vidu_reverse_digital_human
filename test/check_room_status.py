"""使用独立本机会话检查指定房间，仅输出统计，不记录观众内容。"""
import sys
import time
import httpx


def main():
    """启动短时采集，输出房间状态和计数，最后停止自己的采集任务。"""
    room_id = sys.argv[1]  # 命令行提供待验证的直播间数字 ID。
    headers = {"X-Studio-Request": "1"}  # 本地接口要求的同源请求标记。
    with httpx.Client(base_url="http://127.0.0.1:8795", headers=headers, timeout=15) as client:
        client.get("/api/vidu/status").raise_for_status()  # 初始化隔离会话。
        client.post("/api/session/room", json={"room_id": room_id}).raise_for_status()
        try:
            for _ in range(6):  # 每五秒观察一次，最多三十秒。
                time.sleep(5)
                response = client.get("/api/events")
                response.raise_for_status()
                data = response.json()  # 仅展示状态和汇总计数。
                print({key: data[key] for key in ("room_id", "state", "detail", "counts", "queue_size")}, flush=True)
                if data["state"] in ("room_not_found", "room_status_unknown", "disconnected"):
                    break
        finally:
            client.post("/api/session/room/stop").raise_for_status()
            client.post("/api/vidu/logout").raise_for_status()  # 释放本次独立测试会话。


if __name__ == "__main__":
    main()
