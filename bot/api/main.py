from fastapi import FastAPI
from pydantic import BaseModel
from urllib.parse import urlencode
import requests, os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

from data.subscriptions import ServerQueue

class OauthBody(BaseModel):
    code: str


@app.post("/api/token")
def token(oauthBody: OauthBody):
    code = oauthBody.code
    data = {
        "client_id": os.getenv("CLIENT_ID"),
        "client_secret": os.getenv("CLIENT_SECRET"),
        "grant_type": "authorization_code",
        "code": code,
    }
    res = requests.post(
        url="https://discord.com/api/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode(data),
    )
    
    return res.json()

@app.get("/api/test")
def test():
    print(ServerQueue._serverStatus)
    return {}
