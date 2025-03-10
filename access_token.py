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

# 常量配置
BASE_URL = "https://zhcjsmz.sc.yichang.gov.cn"
ACCESS_TOKEN_FILE = "../access_token.json"
DEFAULT_HEADERS = {
    "Host": "zhcjsmz.sc.yichang.gov.cn",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="114"',
    "Accept": "*/*",
    "Content-Type": "application/json;charset=UTF-8",
    "sec-ch-ua-mobile": "?0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.289 Safari/537.36",
    "sec-ch-ua-platform": '"Windows"',
    "Origin": "https://zhcjsmz.sc.yichang.gov.cn",
    "Referer": "https://zhcjsmz.sc.yichang.gov.cn/login/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,vi;q=0.7",
}
CREDENTIALS = {
    "username": "13487283013",
    "encrypted_password": "qnsXYUm303WQpeci1uwc+w=="
}
SCALE_FACTOR = 400 / 310  # 图像缩放系数
POS_Y_OFFSET = 5          # Y轴偏移量
X_ADJUSTMENT = -2.5       # X轴位置调整值

class AESHelper:
    @staticmethod
    def encrypt(plaintext: str, key: str) -> str:
        """AES ECB模式加密"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        return base64.b64encode(
            cipher.encrypt(pad(plaintext.encode(), AES.block_size))
        ).decode()

    @staticmethod
    def decrypt(ciphertext: str, key: str) -> str:
        """AES ECB模式解密"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        return unpad(
            cipher.decrypt(base64.b64decode(ciphertext)), 
            AES.block_size
        ).decode()

class CaptchaSolver:
    @staticmethod
    def generate_client_uuid() -> str:
        """生成客户端UUID"""
        hex_digits = "0123456789abcdef"
        chars = [random.choice(hex_digits) for _ in range(36)]
        chars[8] = chars[13] = chars[18] = chars[23] = "-"
        chars[14] = "4"
        chars[19] = hex_digits[(int(chars[19], 16) & 0x3) | 0x8]
        return f"slider-{''.join(chars)}"

    @staticmethod
    def calculate_position(bg_base64: str, tp_base64: str) -> float:
        """计算验证码位置"""
        try:
            bg_img = CaptchaSolver._decode_image(bg_base64, SCALE_FACTOR)
            tp_img = CaptchaSolver._decode_image(tp_base64, SCALE_FACTOR)
            
            bg_edge = cv2.Canny(bg_img, 50, 400)
            tp_edge = cv2.Canny(tp_img, 50, 400)

            res = cv2.matchTemplate(
                cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB),
                cv2.cvtColor(tp_edge, cv2.COLOR_GRAY2RGB),
                cv2.TM_CCOEFF_NORMED
            )
            _, _, _, max_loc = cv2.minMaxLoc(res)
            return max_loc[0] * (1/SCALE_FACTOR) + X_ADJUSTMENT
        except Exception as e:
            logger.error(f"验证码处理失败: {str(e)}")
            raise

    @staticmethod
    def _decode_image(base64_str: str, scale: float) -> np.ndarray:
        """解码并缩放图像"""
        img_data = base64.b64decode(base64_str)
        img = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
        return cv2.resize(img, (0,0), fx=scale, fy=scale)

class AuthManager:
    @staticmethod
    def get_access_token() -> Optional[str]:
        """获取访问令牌主流程"""
        session = requests.Session()
        try:
            # 初始化验证流程
            client_uuid = CaptchaSolver.generate_client_uuid()
            timestamp = int(time.time() * 1000)

            # 获取验证码数据
            captcha_data = AuthManager._get_captcha_data(
                session, client_uuid, timestamp)
            if not captcha_data:
                return None

            # 计算验证码位置
            position = CaptchaSolver.calculate_position(
                captcha_data["bg_img"], 
                captcha_data["tp_img"]
            )
            
            # 验证验证码
            if not AuthManager._verify_captcha(
                session, position, captcha_data, timestamp):
                return None

            # 获取访问令牌
            return AuthManager._request_token(session, captcha_data)
            
        except Exception as e:
            logger.error(f"认证流程异常: {str(e)}")
            return None
        finally:
            session.close()

    @staticmethod
    def _get_captcha_data(session: requests.Session, 
                         client_uuid: str, 
                         timestamp: int) -> Optional[dict]:
        """获取验证码数据"""
        try:
            response = session.post(
                f"{BASE_URL}/code/create",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": client_uuid,
                    "ts": timestamp
                },
                headers=DEFAULT_HEADERS
            )
            response.raise_for_status()
            data = response.json()["data"]["repData"]
            return {
                "secret_key": data["secretKey"],
                "token": data["token"],
                "bg_img": data["originalImageBase64"],
                "tp_img": data["jigsawImageBase64"]
            }
        except Exception as e:
            logger.error(f"获取验证码失败: {str(e)}")
            return None

    @staticmethod
    def _verify_captcha(session: requests.Session,
                       position: float,
                       captcha_data: dict,
                       timestamp: int) -> bool:
        """验证验证码"""
        try:
            pos_str = json.dumps({"x": position, "y": POS_Y_OFFSET})
            encrypted_pos = AESHelper.encrypt(
                pos_str, 
                captcha_data["secret_key"]
            )

            response = session.post(
                f"{BASE_URL}/code/check",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": captcha_data["clientUid"],
                    "pointJson": encrypted_pos,
                    "token": captcha_data["token"],
                    "ts": timestamp
                },
                headers=DEFAULT_HEADERS
            )
            response.raise_for_status()
            return "执行成功" in response.json().get("msg", "")
        except Exception as e:
            logger.error(f"验证码验证失败: {str(e)}")
            return False

    @staticmethod
    def _request_token(session: requests.Session,
                      captcha_data: dict) -> Optional[str]:
        """请求访问令牌"""
        try:
            captcha = AESHelper.encrypt(
                f"{captcha_data['token']}---{{\"x\":{position}, \"y\":5}}",
                captcha_data["secret_key"]
            )

            headers = DEFAULT_HEADERS.copy()
            headers.update({
                "Authorization": "Basic cGlnOnBpZw==",
                "TENANT-ID": "1"
            })

            response = session.post(
                f"{BASE_URL}/auth/custom/token",
                params={
                    "username": CREDENTIALS["username"],
                    "grant_type": "password",
                    "scope": "server",
                    "code": captcha,
                    "randomStr": "blockPuzzle"
                },
                json={"sskjPassword": CREDENTIALS["encrypted_password"]},
                headers=headers
            )
            response.raise_for_status()
            return response.json()["access_token"]
        except Exception as e:
            logger.error(f"令牌请求失败: {str(e)}")
            return None

def main():
    # 检查现有令牌有效性
    token, timestamp = _read_access_token()
    if token and time.time() - timestamp < 6 * 3600:
        logger.info("有效访问令牌已存在")
        return

    # 获取新令牌
    new_token = AuthManager.get_access_token()
    if new_token:
        _save_access_token(new_token)
        logger.success("访问令牌更新成功")
    else:
        logger.error("未能获取新访问令牌")

def _read_access_token() -> Tuple[Optional[str], int]:
    """读取存储的访问令牌"""
    try:
        with open(ACCESS_TOKEN_FILE, "r") as f:
            data = json.load(f)
            return data.get("access_token"), data.get("timestamp", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return None, 0

def _save_access_token(token: str):
    """保存访问令牌"""
    try:
        with open(ACCESS_TOKEN_FILE, "w") as f:
            json.dump({
                "access_token": token,
                "timestamp": int(time.time())
            }, f)
    except IOError as e:
        logger.error(f"令牌保存失败: {str(e)}")

if __name__ == "__main__":
    main()
