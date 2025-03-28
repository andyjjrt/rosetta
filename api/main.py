from fastapi import FastAPI
from pydantic import BaseModel
from urllib.parse import urlencode
import requests
import os
from dotenv import load_dotenv
from utils.subscriptions import Subscription

load_dotenv()
app = FastAPI()


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
    print(Subscription._serverStatus)
    return {}
