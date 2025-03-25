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
from pathlib import Path
import io
import time
from datetime import datetime, timedelta

# 配置参数
max_attempts = 20
idCardSign = "MDoCAQEwEgIBATAKBggqgRzPVQFoAQoBAQMhALC5L1lSMTEQLmI33J1qUDVhRVwTyt+e+27ntIC3g2Wb"
BASE_url = "https://zhcjsmz.sc.yichang.gov.cn"
login_url = "https://zhcjsmz.sc.yichang.gov.cn/labor/workordereng/getEngsPageByUser"
wexinqq_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9b81f009-c046-4812-8690-76763d6b1abd"

headers = {
    "Host": "zhcjsmz.sc.yichang.gov.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.289 Safari/537.36",
    "Authorization": "Basic cGlnOnBpZw=="
}

# ================== Token 管理 ==================
def save_token(access_token, expires_in):
    """保存Token及相关时间信息"""
    token_data = {
        'access_token': access_token,
        'expiry_time': time.time() + expires_in,
        'obtained_time': time.time()
    }
    with open('token.json', 'w') as f:
        json.dump(token_data, f)

def load_token():
    """加载本地存储的Token"""
    try:
        with open('token.json', 'r') as f:
            token_data = json.load(f)
            # 验证必要字段存在
            if all(key in token_data for key in ['access_token', 'expiry_time', 'obtained_time']):
                return token_data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None

def is_token_valid(token_data):
    """检查Token是否有效（12小时机制）"""
    if not token_data:
        return False
    current_time = time.time()
    # Token有效期剩余至少5分钟 且 未超过12小时
    return (token_data['expiry_time'] > current_time + 300) and \
           (current_time - token_data['obtained_time'] < 12 * 3600)

# ================== 加解密函数 ==================
def aes_encrypt(word, key_word):
    key = bytes(key_word, 'utf-8')
    cipher = AES.new(key, AES.MODE_ECB)
    return base64.b64encode(cipher.encrypt(pad(word.encode(), AES.block_size))).decode()

def aes_decrypt(ciphertext, key_word):
    key = bytes(key_word, 'utf-8')
    cipher = AES.new(key, AES.MODE_ECB)
    return unpad(cipher.decrypt(base64.b64decode(ciphertext)), AES.block_size).decode()

# ================== 验证码处理 ==================
def generate_client_uuid():
    """生成客户端UUID"""
    return f"slider-{''.join(random.choices('0123456789abcdef', k=8))}" \
           f"-{''.join(random.choices('0123456789abcdef', k=4))}" \
           f"-4{''.join(random.choices('0123456789abcdef', k=3))}" \
           f"-{random.choice('89ab')}{''.join(random.choices('0123456789abcdef', k=3))}" \
           f"-{''.join(random.choices('0123456789abcdef', k=12))}"

def getImgPos(bg, tp, scale_factor=400/310):
    """计算滑块验证缺口位置"""
    try:
        # Base64解码
        bg_data = base64.b64decode(bg)
        tp_data = base64.b64decode(tp)
        
        # 数据有效性检查
        if len(bg_data) == 0 or len(tp_data) == 0:
            logger.error("空图像数据")
            return 0

        # 图像解码
        bg_img = cv2.imdecode(np.frombuffer(bg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
        tp_img = cv2.imdecode(np.frombuffer(tp_data, dtype=np.uint8), cv2.IMREAD_COLOR)
        
        if bg_img is None:
            logger.error("背景图解码失败")
            return 0
        if tp_img is None:
            logger.error("缺口图解码失败")
            return 0

        # 图像缩放
        bg_img = cv2.resize(bg_img, None, fx=scale_factor, fy=scale_factor)
        tp_img = cv2.resize(tp_img, None, fx=scale_factor, fy=scale_factor)

        # 边缘检测
        bg_edge = cv2.Canny(bg_img, 50, 400)
        tp_edge = cv2.Canny(tp_img, 50, 400)

        # 颜色空间转换
        bg_pic = cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB)
        tp_pic = cv2.cvtColor(tp_edge, cv2.COLOR_GRAY2RGB)

        # 模板匹配
        res = cv2.matchTemplate(bg_pic, tp_pic, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        # 计算最终位置
        x_pos = max_loc[0] * (310 / 400) - 2.5
        logger.success(f"计算成功，缺口位置: {x_pos}")
        return x_pos

    except Exception as e:
        logger.error(f"图像处理异常: {str(e)}")
        return 0

# ================== 通知发送 ==================
def send_wexinqq_md(content):
    """发送Markdown消息到企业微信"""
    return requests.post(
        wexinqq_url,
        json={'msgtype': 'markdown', 'markdown': {'content': content}}
    ).json()

# ================== 数据监控 ==================
def load_existing_ids():
    """加载已记录的ID集合"""
    try:
        with open('ids.json') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_new_ids(ids):
    """保存新的ID集合"""
    with open('ids.json', 'w') as f:
        json.dump(list(ids), f)

def fetch_all_records(access_token):
    """获取所有分页数据"""
    headers = {
        "Authorization": f"bearer {access_token}",
        **{k:v for k,v in headers.items() if k != "Authorization"}
    }
    
    all_records = []

    while True:
        try:
            resp = requests.get(
                f"{login_url}?page=1&limit=10"
                f"&idCardSign={idCardSign}&orderByField=verifyTime&isAsc=false",
                headers=headers
            ).json()
            records = resp.get('data', {}).get('records', [])
            if not records:
                break
            all_records.extend(records)
        except Exception as e:
            logger.error(f"获取数据失败: {e}")
            break
    return all_records

def check_new_records(access_token):
    """检查新记录并发送通知"""
    existing_ids = load_existing_ids()
    current_ids = set()
    new_records = []
    
    for record in fetch_all_records(access_token):
        record_id = record.get('id')
        if not record_id:
            continue
        current_ids.add(record_id)
        if record_id not in existing_ids:
            new_records.append(record)
    
    if new_records:
        messages = []
        for r in new_records:
            timestamp = r['verifyTime']/1000
            messages.append(
                f"**新考勤记录**\n"
                f"> 姓名：{r.get('name', '未知')}\n"
                f"> 工种：{r.get('jobName', '未知')}\n"
                f"> 时间：{datetime.fromtimestamp(timestamp):%Y-%m-%d %H:%M:%S}\n"
                f"> 状态：{'进入' if r.get('inOrOut') == 'in' else '离开'}"
            )
        
        send_result = send_wexinqq_md("\n\n".join(messages))
        if send_result.get('errcode') == 0:
            save_new_ids(existing_ids.union(current_ids))
            return True
        logger.error(f"消息发送失败: {send_result}")
    return False

# ================== Token获取主流程 ==================
def refresh_token():
    """刷新Token主流程"""
    for attempt in range(1, max_attempts+1):
        logger.info(f"Token获取尝试第{attempt}次")
        session = requests.Session()
        try:
            # 验证码获取
            clientUUID = generate_client_uuid()
            captcha_resp = session.post(
                f"{BASE_url}/code/create",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": clientUUID,
                    "ts": int(time.time()*1000)
                }
            ).json()
            
            # 图像识别
            pos = getImgPos(
                captcha_resp['data']['repData']['originalImageBase64'],
                captcha_resp['data']['repData']['jigsawImageBase64']
            )
            encrypted_pos = aes_encrypt(
                f'{{"x":{pos},"y":5}}',
                captcha_resp['data']['repData']['secretKey']
            )
            
            # 验证码校验
            check_resp = session.post(
                f"{BASE_url}/code/check",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": clientUUID,
                    "pointJson": encrypted_pos,
                    "token": captcha_resp['data']['repData']['token'],
                    "ts": int(time.time()*1000)
                }
            ).json()
            
            # Token获取
            token_resp = session.post(
                f"{BASE_url}/auth/custom/token",
                params={
                    "username": "13487283013",
                    "grant_type": "password",
                    "scope": "server",
                    "code": aes_encrypt(
                        f"{captcha_resp['data']['repData']['token']}---{{'x':{pos},'y':5}}",
                        captcha_resp['data']['repData']['secretKey']
                    ),
                    "randomStr": "blockPuzzle"
                },
                json={"sskjPassword": "2giTy1DTppbddyVBc0F6gMdSpT583XjDyJJxME2ocJ4="}
            ).json()
            
            if 'access_token' in token_resp:
                save_token(token_resp['access_token'], token_resp.get('expires_in', 7200))
                return token_resp['access_token']
        except Exception as e:
            logger.error(f"尝试{attempt}失败: {str(e)}")
            time.sleep(random.uniform(1, 5))
    raise Exception("无法获取有效Token")

# ================== 主循环 ==================
def main():
    while True:
        try:
            # Token有效性检查
            token_data = load_token()
            if not is_token_valid(token_data):
                logger.info("Token无效或已过期，需要刷新")
                access_token = refresh_token()
            else:
                access_token = token_data['access_token']
            
            # 数据检查
            if check_new_records(access_token):
                logger.success("发现新记录并成功通知")
            else:
                logger.info("未发现新记录")
            
            # 间隔5分钟
            time.sleep(300)
        except KeyboardInterrupt:
            logger.info("程序已手动终止")
            break
        except Exception as e:
            logger.error(f"主循环异常: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    main()
