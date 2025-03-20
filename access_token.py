from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64
import requests
import json
import random
import os
import time
import cv2
import numpy as np
from pathlib import Path
from loguru import logger
from PIL import Image
import io
from typing import Optional, Dict, Tuple

# 环境变量配置（生产环境应通过外部设置）
os.environ.update({
    "AUTH_USER": "13487283013",
    "AUTH_PWD": "YCsmz@#Zhou88910440",
    "SSKJ_SECRET": "2giTy1DTppbddyVBc0F6gMdSpT583XjDyJJxME2ocJ4="
})

# 全局配置常量
CONFIG = {
    "base_url": "https://zhcjsmz.sc.yichang.gov.cn",
    "token_file": Path(os.path.expanduser("~/access_token.json")),
    "api_timeout": 15,
    "retry": {
        "max_attempts": 5,
        "initial_delay": 2,
        "backoff_factor": 2
    },
    "captcha": {
        "scale_factor": 400/310,
        "base_width": 310,
        "edge_threshold": (50, 200),
        "min_confidence": 0.4,
        "offset": 2.5
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
        "Referer": "https://zhcjsmz.sc.yichang.gov.cn/login/",
    },
    "auth_headers": {
        "Authorization": "Basic cGlnOnBpZw==",
        "TENANT-ID": "1"
    }
}

class CryptoUtils:
    """加解密工具类"""
    
    @staticmethod
    def aes_encrypt(plaintext: str, key: str) -> str:
        """AES-ECB加密"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        padded = pad(plaintext.encode(), AES.block_size)
        return base64.b64encode(cipher.encrypt(padded)).decode()

    @staticmethod
    def aes_decrypt(ciphertext: str, key: str) -> str:
        """AES-ECB解密"""
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        decrypted = cipher.decrypt(base64.b64decode(ciphertext))
        return unpad(decrypted, AES.block_size).decode()

class CaptchaHandler:
    """验证码处理模块"""
    
    _CALIBRATION_FACTOR = 0.2  # 校准学习率
    
    def __init__(self):
        self.offset = CONFIG["captcha"]["offset"]
        
    @staticmethod
    def generate_uuid() -> str:
        """生成验证码客户端UUID"""
        chars = [random.choice("0123456789abcdef") for _ in range(36)]
        uuid_pattern = [8, 13, 18, 23]
        for pos in uuid_pattern:
            chars[pos] = "-"
        chars[14] = "4"
        chars[19] = f"{int(chars[19], 16) & 0x3 | 0x8:x}"
        return f"slider-{''.join(chars)}"

    def analyze_position(self, bg_base64: str, tp_base64: str) -> Optional[float]:
        """分析验证码缺口位置"""
        try:
            # 图像解码
            bg_img = self._decode_image(bg_base64)
            tp_img = self._decode_image(tp_base64)
            
            # 图像预处理
            bg_processed = self._preprocess_image(bg_img)
            tp_processed = self._preprocess_image(tp_img)
            
            # 模板匹配
            result = cv2.matchTemplate(bg_processed, tp_processed, cv2.TM_CCOEFF_NORMED)
            confidence = np.max(result)
            
            if confidence < CONFIG["captcha"]["min_confidence"]:
                raise ValueError(f"可信度过低: {confidence:.2f}")
                
            _, _, _, max_loc = cv2.minMaxLoc(result)
            return max_loc[0] - self.offset
        except Exception as e:
            logger.error(f"验证码分析失败: {str(e)}")
            return None

    def calibrate_offset(self, actual_pos: float, detected_pos: float):
        """校准偏移量"""
        self.offset += (actual_pos - detected_pos) * self._CALIBRATION_FACTOR
        logger.info(f"校准偏移量至: {self.offset:.2f}px")

    def _decode_image(self, base64_str: str) -> np.ndarray:
        """Base64解码图像"""
        img_data = base64.b64decode(base64_str)
        img = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
        return cv2.resize(
            img, 
            (0,0), 
            fx=CONFIG["captcha"]["scale_factor"], 
            fy=CONFIG["captcha"]["scale_factor"]
        )

    def _preprocess_image(self, img: np.ndarray) -> np.ndarray:
        """图像预处理流程"""
        # 高斯模糊降噪
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        # 边缘检测
        edges = cv2.Canny(blurred, *CONFIG["captcha"]["edge_threshold"])
        # 形态学操作
        kernel = np.ones((3,3), np.uint8)
        return cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

class AuthClient:
    """认证客户端主类"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(CONFIG["headers"])
        self.captcha_handler = CaptchaHandler()
        self._init_token_file()

    def _init_token_file(self):
        """初始化令牌存储文件"""
        try:
            CONFIG["token_file"].parent.mkdir(parents=True, exist_ok=True)
            CONFIG["token_file"].touch(exist_ok=True)
        except PermissionError:
            logger.critical("缺少文件写入权限")
            raise

    def get_access_token(self) -> Optional[str]:
        """获取访问令牌（主入口）"""
        if token := self._read_cached_token():
            return token
            
        return self._acquire_new_token_with_retry()

    def _read_cached_token(self) -> Optional[str]:
        """读取缓存的访问令牌"""
        try:
            with open(CONFIG["token_file"], "r") as f:
                data = json.load(f)
                if time.time() - data["timestamp"] < 6 * 3600:
                    logger.info("使用有效缓存令牌")
                    return data["access_token"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        return None

    def _acquire_new_token_with_retry(self) -> Optional[str]:
        """带重试的认证流程"""
        attempt = 1
        max_retries = CONFIG["retry"]["max_attempts"]
        while attempt <= max_retries:
            logger.info(f"认证尝试 {attempt}/{max_retries}")
            
            try:
                # 获取验证码数据
                captcha_data = self._get_captcha_data()
                if not captcha_data:
                    continue
                
                # 验证验证码
                if not self._verify_captcha(captcha_data):
                    continue
                
                # 获取访问令牌
                if token := self._request_token(captcha_data):
                    return token
                    
            except requests.RequestException as e:
                logger.error(f"网络请求异常: {str(e)}")
            except cv2.error as e:
                logger.critical(f"OpenCV错误: {str(e)}")
                break

            # 指数退避重试
            delay = CONFIG["retry"]["initial_delay"] * (CONFIG["retry"]["backoff_factor"] ** (attempt-1))
            logger.warning(f"{delay:.1f}秒后重试...")
            time.sleep(delay)
            attempt += 1
            
        logger.error("超过最大重试次数")
        return None

    def _get_captcha_data(self) -> Optional[Dict]:
        """获取验证码数据"""
        client_uuid = CaptchaHandler.generate_uuid()
        try:
            resp = self.session.post(
                f"{CONFIG['base_url']}/code/create",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": client_uuid,
                    "ts": int(time.time() * 1000)
                },
                timeout=CONFIG["api_timeout"]
            )
            resp.raise_for_status()
            
            data = resp.json()["data"]["repData"]
            logger.info(f"验证码数据:{data['token']}")
            return {
                "client_uuid": client_uuid,
                "secret_key": data["secretKey"],
                "token": data["token"],
                "bg_img": data["originalImageBase64"],
                "tp_img": data["jigsawImageBase64"]
            }
            
        except (KeyError, requests.RequestException) as e:
            logger.error(f"获取验证码失败: {str(e)}")
            return None

    def _verify_captcha(self, data: Dict) -> bool:
        """验证验证码"""
        for _ in range(CONFIG["retry"]["max_attempts"]):
            position = self.captcha_handler.analyze_position(data["bg_img"], data["tp_img"])
            if position is None:
                continue
                
            calibrated_pos = position * (CONFIG["captcha"]["base_width"] / 400)
            pos_json = json.dumps({"x": calibrated_pos, "y": 5})
            
            try:
                resp = self.session.post(
                    f"{CONFIG['base_url']}/code/check",
                    json={
                        "captchaType": "blockPuzzle",
                        "clientUid": data["client_uuid"],
                        "pointJson": CryptoUtils.aes_encrypt(pos_json, data["secret_key"]),
                        "token": data["token"],
                        "ts": int(time.time() * 1000)
                    },
                    timeout=CONFIG["api_timeout"]
                )
                
                if resp.status_code == 412:
                    logger.warning("验证码不匹配")
                    continue
                    
                resp.raise_for_status()
                return resp.json().get("msg") == "执行成功"
                
            except requests.HTTPError as e:
                logger.error(f"验证请求失败: {e.response.text}")
                
        return False

    def _request_token(self, data: Dict) -> Optional[str]:
        """请求访问令牌"""
        try:
            auth_payload = f"{data['token']}---{json.dumps({'x': 0, 'y': 5})}"
            encrypted_code = CryptoUtils.aes_encrypt(auth_payload, data["secret_key"])
            
            self.session.headers.update(CONFIG["auth_headers"])
            resp = self.session.post(
                f"{CONFIG['base_url']}/auth/custom/token",
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
            
            token_data = resp.json()
            access_token = token_data["access_token"]
            self._save_token(access_token)
            return access_token
            
        except (KeyError, requests.RequestException) as e:
            logger.error(f"令牌请求失败: {str(e)}")
            return None

    def _save_token(self, token: str):
        """安全存储访问令牌"""
        try:
            with open(CONFIG["token_file"], "w") as f:
                json.dump({
                    "access_token": token,
                    "timestamp": int(time.time())
                }, f, indent=2)
            logger.success("令牌存储成功")
        except IOError as e:
            logger.error(f"存储令牌失败: {str(e)}")

if __name__ == "__main__":
    try:
        client = AuthClient()
        if token := client.get_access_token():
            logger.success(f"认证成功！令牌前8位: {token[:8]}...")
        else:
            logger.error("认证失败")
            exit(1)
    except Exception as e:
        logger.critical(f"程序异常终止: {str(e)}")
        exit(1)
