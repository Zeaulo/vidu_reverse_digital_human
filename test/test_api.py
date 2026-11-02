"""FastAPI 基础接口测试。"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    """验证健康检查接口返回运行状态。"""
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_room_id_must_be_numeric():
    """验证房间 ID 输入校验。"""
    response = TestClient(app).post("/api/session/room", json={"room_id": "abc"})
    assert response.status_code == 400
