from fastapi import FastAPI, Query, Header
from typing import Optional

app = FastAPI(title="Mock API")

@app.get("/v1/status")
async def get_status(
    keyword: str = Query(..., description="使用者的查詢關鍵字"),
    
    authorization: Optional[str] = Header(None)
):
    print(f"\n[Mock API 收到請求] 關鍵字: {keyword}")
    if authorization:
        print(f"  └ 收到驗證碼: {authorization}")
    else:
        print("  └ (沒有收到驗證碼)")

    if "訂單" in keyword:
        fake_result = "您的訂單 (編號: SN-20240501) 目前已出貨，預計明天下午由黑貓宅急便送達。"
    elif "維修" in keyword:
        fake_result = "您的維修申請 (單號: R-9988) 已經派工，工程師將於今日下午 14:00 與您電話聯繫。"
    else:
        fake_result = "很抱歉，在訂單系統中查無相關資訊，請提供您的訂單編號。"

    return {
        "status": "success",
        "message": fake_result
    }