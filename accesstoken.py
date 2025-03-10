from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64
import requests
import json
import random
from loguru import logger
import cv2
import numpy as np
import os
from PIL import Image
import io
import time
from datetime import datetime
from typing import Tuple, Optional

# 常量定义
BASE_URL = "https://zhcjsmz.sc.yichang.gov.cn"
DEFAULT_HEADERS = {
    "Host": "zhcjsmz.sc.yichang.gov.cn",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="114"',
    "Accept": "*/*",
    "Content-Type": "application/json;charset=UTF-8",
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.289 Safari/537.36",
    "sec-ch-ua-platform": '"Windows"',
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/login/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,vi;q=0.7",
}
TOKEN_FILE = "access_token.json"
TOKEN_EXPIRE_SECONDS = 6 * 60 * 60  # 6小时
IMAGE_SCALE_FACTOR = 400 / 310  # 图像缩放比例
CAPTCHA_OFFSET = 2.5  # 验证码坐标偏移量

class CaptchaSolver:
    @staticmethod
    def aes_encrypt(plaintext: str, key: str) -> str:
        """AES ECB模式加密"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        padded_data = pad(plaintext.encode(), AES.block_size)
        encrypted = cipher.encrypt(padded_data)
        return base64.b64encode(encrypted).decode()

    @staticmethod
    def aes_decrypt(ciphertext: str, key: str) -> str:
        """AES ECB模式解密"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        decrypted = cipher.decrypt(base64.b64decode(ciphertext))
        return unpad(decrypted, AES.block_size).decode()

    @staticmethod
    def generate_client_uuid() -> str:
        """生成客户端UUID"""
        hex_digits = "0123456789abcdef"
        chars = [random.choice(hex_digits) for _ in range(36)]
        chars[8] = chars[13] = chars[18] = chars[23] = "-"
        chars[14] = "4"
        chars[19] = f"{int(chars[19], 16) & 0x3 | 0x8:x}"
        return f"slider-{''.join(chars)}"

    @staticmethod
    def process_captcha_images(bg_base64: str, tp_base64: str) -> float:
        """处理验证码图像并返回缺口位置"""
        def decode_image(base64_str: str) -> np.ndarray:
            return cv2.imdecode(np.frombuffer(base64.b64decode(base64_str), cv2.IMREAD_COLOR)

        bg_img = cv2.resize(decode_image(bg_base64), (0,0), fx=IMAGE_SCALE_FACTOR, fy=IMAGE_SCALE_FACTOR)
        tp_img = cv2.resize(decode_image(tp_base64), (0,0), fx=IMAGE_SCALE_FACTOR, fy=IMAGE_SCALE_FACTOR)

        # 边缘检测
        bg_edge = cv2.Canny(bg_img, 50, 400)
        tp_edge = cv2.Canny(tp_img, 50, 400)

        # 模板匹配
        result = cv2.matchTemplate(
            cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB),
            cv2.cvtColor(tp_edge, cv2.COLOR_GRAY2RGB),
            cv2.TM_CCOEFF_NORMED
        )
        _, _, _, max_loc = cv2.minMaxLoc(result)
        return max_loc[0] - CAPTCHA_OFFSET

class AuthManager:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get_access_token(self) -> Optional[str]:
        """获取访问令牌"""
        try:
            # 检查本地令牌
            if token := self._read_local_token():
                return token

            # 初始化验证流程
            client_uuid = CaptchaSolver.generate_client_uuid()
            timestamp = int(time.time() * 1000)
            
            # 获取验证码
            captcha_data = self._get_captcha(client_uuid, timestamp)
            if not captcha_data:
                return None

            # 验证验证码
            if not self._verify_captcha(client_uuid, timestamp, captcha_data):
                return None

            # 获取访问令牌
            return self._request_access_token(captcha_data)

        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            return None

    def _get_captcha(self, client_uuid: str, timestamp: int) -> Optional[dict]:
        """获取验证码数据"""
        response = self.session.post(
            f"{BASE_URL}/code/create",
            json={
                "captchaType": "blockPuzzle",
                "clientUid": client_uuid,
                "ts": timestamp
            },
            timeout=10
        )
        if not response.ok:
            logger.error(f"Failed to get captcha: {response.text}")
            return None

        data = response.json().get("data", {}).get("repData", {})
        return {
            "secret_key": data.get("secretKey"),
            "token": data.get("token"),
            "bg_img": data.get("originalImageBase64"),
            "tp_img": data.get("jigsawImageBase64")
        }

    def _verify_captcha(self, client_uuid: str, timestamp: int, captcha_data: dict) -> bool:
        """验证验证码"""
        pos_x = CaptchaSolver.process_captcha_images(captcha_data["bg_img"], captcha_data["tp_img"])
        pos_str = json.dumps({"x": pos_x * (310/400), "y": 5})
        
        verify_data = {
            "captchaType": "blockPuzzle",
            "clientUid": client_uuid,
            "pointJson": CaptchaSolver.aes_encrypt(pos_str, captcha_data["secret_key"]),
            "token": captcha_data["token"],
            "ts": timestamp
        }

        response = self.session.post(
            f"{BASE_URL}/code/check",
            json=verify_data,
            timeout=10
        )
        return response.json().get("msg") == "执行成功"

    def _request_access_token(self, captcha_data: dict) -> Optional[str]:
        """请求访问令牌"""
        self.session.headers.update({
            "Authorization": "Basic cGlnOnBpZw==",
            "TENANT-ID": "1"
        })

        response = self.session.post(
            f"{BASE_URL}/auth/custom/token",
            params={
                "username": "13487283013",
                "grant_type": "password",
                "scope": "server",
                "code": CaptchaSolver.aes_encrypt(
                    f"{captcha_data['token']}---{json.dumps({'x': 0, 'y': 5})}",
                    captcha_data["secret_key"]
                ),
                "randomStr": "blockPuzzle"
            },
            json={"sskjPassword": "qnsXYUm303WQpeci1uwc+w=="},
            timeout=10
        )

        if not response.ok:
            return None

        token_data = response.json()
        if "access_token" not in token_data:
            return None

        self._save_token(token_data["access_token"])
        return token_data["access_token"]

    @staticmethod
    def _read_local_token() -> Optional[str]:
        """读取本地存储的令牌"""
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                if time.time() - data["timestamp"] < TOKEN_EXPIRE_SECONDS:
                    return data["access_token"]
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    def _save_token(token: str) -> None:
        """保存令牌到本地文件"""
        with open(TOKEN_FILE, "w") as f:
            json.dump({
                "access_token": token,
                "timestamp": int(time.time())
            }, f)

if __name__ == "__main__":
    auth = AuthManager()
    if token := auth.get_access_token():
        logger.success(f"Access token acquired: {token[:15]}...")
    else:
        logger.error("Failed to get access token")
