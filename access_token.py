from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64
import requests
import json
import random
import os
from pathlib import Path
from loguru import logger
import cv2
import numpy as np
from PIL import Image
import io
import time
from datetime import datetime
from typing import Optional, Dict

# 安全配置（建议通过环境变量设置）
os.environ.update({
    "AUTH_USER": "13487283013",
    "AUTH_PWD": "YCsmz@#Zhou88910440",
    "SSKJ_SECRET": "2giTy1DTppbddyVBc0F6gMdSpT583XjDyJJxME2ocJ4="
})

# 常量配置
BASE_URL = "https://zhcjsmz.sc.yichang.gov.cn"
CONFIG = {
    "token_file": Path(__file__).parent.parent / "access_token.json",
    "token_ttl": 6 * 60 * 60,  # 6小时有效期
    "api_timeout": 15,
    "captcha": {
        "scale": 400/310,
        "offset": 2.5,
        "edge_threshold": (50, 400)
    },
    "credentials": {
        "username": os.getenv("AUTH_USER"),
        "password": os.getenv("AUTH_PWD"),
        "sskj_secret": os.getenv("SSKJ_SECRET")
    },
    "headers": {
        "Host": "zhcjsmz.sc.yichang.gov.cn",
        "Accept": "*/*",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.289 Safari/537.36",
        "Referer": f"{BASE_URL}/login/",
    },
    "auth_headers": {
        "Authorization": "Basic cGlnOnBpZw==",
        "TENANT-ID": "1"
    }
}

class CryptoHelper:
    @staticmethod
    def aes_encrypt(plaintext: str, key: str) -> str:
        """AES-ECB加密（PKCS7填充）"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        return base64.b64encode(
            cipher.encrypt(pad(plaintext.encode(), AES.block_size))
        ).decode()

    @staticmethod
    def aes_decrypt(ciphertext: str, key: str) -> str:
        """AES-ECB解密（PKCS7填充）"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        return unpad(
            cipher.decrypt(base64.b64decode(ciphertext)),
            AES.block_size
        ).decode()

class CaptchaProcessor:
    @staticmethod
    def generate_uuid() -> str:
        """生成符合规范的验证码客户端UUID"""
        chars = [random.choice("0123456789abcdef") for _ in range(36)]
        uuid_pattern = [8, 13, 18, 23]  # 分隔符位置
        for pos in uuid_pattern:
            chars[pos] = "-"
        chars[14] = "4"  # 版本标识
        chars[19] = f"{int(chars[19], 16) & 0x3 | 0x8:x}"  # 变体标识
        return f"slider-{''.join(chars)}"

    @staticmethod
    def analyze_position(bg_base64: str, tp_base64: str) -> float:
        """分析验证码缺口位置"""
        def decode_image(data: str) -> np.ndarray:
            img_data = base64.b64decode(data)
            return cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)

        try:
            # 图像预处理
            bg = cv2.resize(
                decode_image(bg_base64), 
                (0,0), 
                fx=CONFIG["captcha"]["scale"], 
                fy=CONFIG["captcha"]["scale"]
            )
            tp = cv2.resize(
                decode_image(tp_base64),
                (0,0),
                fx=CONFIG["captcha"]["scale"],
                fy=CONFIG["captcha"]["scale"]
            )

            # 边缘检测
            bg_edge = cv2.Canny(bg, *CONFIG["captcha"]["edge_threshold"])
            tp_edge = cv2.Canny(tp, *CONFIG["captcha"]["edge_threshold"])

            # 模板匹配
            match_result = cv2.matchTemplate(
                cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB),
                cv2.cvtColor(tp_edge, cv2.COLOR_GRAY2RGB),
                cv2.TM_CCOEFF_NORMED
            )
            _, _, _, max_loc = cv2.minMaxLoc(match_result)
            return max_loc[0] - CONFIG["captcha"]["offset"]
        except cv2.error as e:
            logger.error(f"OpenCV处理错误: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"验证码分析异常: {str(e)}")
            raise

class AuthClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(CONFIG["headers"])
        self._init_token_storage()

    def _init_token_storage(self):
        """初始化令牌存储文件"""
        try:
            CONFIG["token_file"].parent.mkdir(parents=True, exist_ok=True)
            CONFIG["token_file"].touch(exist_ok=True)
        except PermissionError as e:
            logger.critical(f"文件权限异常: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"存储初始化失败: {str(e)}")
            raise

    def get_access_token(self) -> Optional[str]:
        """获取访问令牌主入口"""
        if cached_token := self._get_cached_token():
            return cached_token
        
        try:
            return self._acquire_new_token()
        except requests.RequestException as e:
            logger.error(f"网络请求异常: {str(e)}")
        except json.JSONDecodeError:
            logger.error("响应数据解析失败")
        except KeyError as e:
            logger.error(f"响应数据缺少关键字段: {str(e)}")
        return None

    def _get_cached_token(self) -> Optional[str]:
        """获取已缓存的令牌"""
        try:
            with open(CONFIG["token_file"], "r") as f:
                token_data = json.load(f)
                if time.time() - token_data["timestamp"] < CONFIG["token_ttl"]:
                    logger.info("使用有效缓存令牌")
                    return token_data["access_token"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        return None

    def _acquire_new_token(self) -> Optional[str]:
        """执行完整认证流程"""
        client_uuid = CaptchaProcessor.generate_uuid()
        timestamp = int(time.time() * 1000)

        # 获取验证码数据
        captcha_data = self._fetch_captcha_data(client_uuid, timestamp)
        if not captcha_data:
            return None

        # 验证验证码
        if not self._verify_captcha(client_uuid, timestamp, captcha_data):
            return None

        # 获取访问令牌
        return self._request_access_token(captcha_data)

    def _fetch_captcha_data(self, client_uuid: str, ts: int) -> Optional[Dict]:
        """获取验证码数据"""
        try:
            resp = self.session.post(
                f"{BASE_URL}/code/create",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": client_uuid,
                    "ts": ts
                },
                timeout=CONFIG["api_timeout"]
            )
            resp.raise_for_status()

            response_data = resp.json()
            return {
                "secret_key": response_data["data"]["repData"]["secretKey"],
                "token": response_data["data"]["repData"]["token"],
                "bg_img": response_data["data"]["repData"]["originalImageBase64"],
                "tp_img": response_data["data"]["repData"]["jigsawImageBase64"]
            }
        except requests.HTTPError as e:
            logger.error(f"验证码获取失败: {e.response.text}")
            return None

    def _verify_captcha(self, client_uuid: str, ts: int, data: Dict) -> bool:
        """执行验证码验证"""
        try:
            # 计算缺口位置
            raw_pos = CaptchaProcessor.analyze_position(data["bg_img"], data["tp_img"])
            calibrated_pos = raw_pos * (310/400)  # 坐标校准

            # 构造加密数据
            pos_json = json.dumps({"x": calibrated_pos, "y": 5})
            encrypted_pos = CryptoHelper.aes_encrypt(pos_json, data["secret_key"])

            # 提交验证
            resp = self.session.post(
                f"{BASE_URL}/code/check",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": client_uuid,
                    "pointJson": encrypted_pos,
                    "token": data["token"],
                    "ts": ts
                },
                timeout=CONFIG["api_timeout"]
            )
            resp.raise_for_status()
            return resp.json().get("msg") == "执行成功"
        except requests.HTTPError as e:
            logger.error(f"验证码验证失败: {e.response.text}")
            return False

    def _request_access_token(self, captcha_data: Dict) -> Optional[str]:
        """请求最终访问令牌"""
        self.session.headers.update(CONFIG["auth_headers"])

        try:
            # 构造加密凭证
            auth_payload = f"{captcha_data['token']}---{json.dumps({'x': 0, 'y': 5})}"
            encrypted_code = CryptoHelper.aes_encrypt(auth_payload, captcha_data["secret_key"])

            # 发送认证请求
            resp = self.session.post(
                f"{BASE_URL}/auth/custom/token",
                params={
                    "username": CONFIG["credentials"]["username"],
                    "grant_type": "password",
                    "scope": "server",
                    "code": encrypted_code,
                    "randomStr": "blockPuzzle"
                },
                json={
                    "sskjPassword": CONFIG["credentials"]["sskj_secret"],
                    "password": CONFIG["credentials"]["password"]
                },
                timeout=CONFIG["api_timeout"]
            )
            resp.raise_for_status()

            # 处理响应数据
            token_data = resp.json()
            if "access_token" not in token_data:
                logger.error("令牌响应格式异常")
                return None

            self._store_token(token_data["access_token"])
            return token_data["access_token"]
        except requests.HTTPError as e:
            logger.error(f"令牌请求失败: {e.response.text}")
            return None

    def _store_token(self, token: str):
        """安全存储访问令牌"""
        try:
            with open(CONFIG["token_file"], "w") as f:
                json.dump({
                    "access_token": token,
                    "timestamp": int(time.time())
                }, f, indent=2)
            logger.success("令牌存储成功")
        except IOError as e:
            logger.error(f"令牌存储失败: {str(e)}")
            raise

if __name__ == "__main__":
    try:
        auth_client = AuthClient()
        if access_token := auth_client.get_access_token():
            logger.success(f"认证成功，令牌前8位: {access_token[:8]}...")
        else:
            logger.error("认证流程失败")
            exit(1)
    except Exception as e:
        logger.critical(f"程序异常终止: {str(e)}")
        exit(1)
