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
max_attempts = 10
idCardSign = "MDoCAQEwEgIBATAKBggqgRzPVQFoAQoBAQMhALC5L1lSMTEQLmI33J1qUDVhRVwTyt+e+27ntIC3g2Wb"
BASE_url = "https://zhcjsmz.sc.yichang.gov.cn"
login_url = "https://zhcjsmz.sc.yichang.gov.cn/labor/workordereng/getEngsPageByUser"
wexinqq_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9b81f009-c046-4812-8690-76763d6b1abd"

headers = {
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
 "Accept-Encoding": "gzip, deflate",
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
 srcs = bytes(word, 'utf-8')
 cipher = AES.new(key, AES.MODE_ECB)
 encrypted = cipher.encrypt(pad(srcs, AES.block_size))
 return base64.b64encode(encrypted).decode('utf-8')

def aes_decrypt(ciphertext, key_word):
 key = bytes(key_word, 'utf-8')
 ciphertext = base64.b64decode(ciphertext)
 cipher = AES.new(key, AES.MODE_ECB)
 decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
 return decrypted.decode('utf-8')

# ================== 验证码处理 ==================
def generate_client_uuid():
    """生成客户端UUID"""
    s = []
    hex_digits = "0123456789abcdef"
    for i in range(36):
     s.append(hex_digits[random.randint(0, 15)])
    s[14] = "4"  # time_hi_and_version字段的12-15位设置为0010
    s[19] = hex_digits[(int(s[19], 16) & 0x3) | 0x8]  # clock_seq_hi_and_reserved字段的6-7位设置为01
    s[8] = s[13] = s[18] = s[23] = "-"
    return 'slider-' + ''.join(s)

# 获取图片函数
def getImgPos(bg, tp, scale_factor):
 '''
 bg: 背景图片
 tp: 缺口图片
 out:输出图片
 '''
 # 解码Base64字符串为字节对象
 bg = base64.b64decode(bg)
 tp = base64.b64decode(tp)

 # 读取背景图片和缺口图片
 bg_img = cv2.imdecode(np.frombuffer(bg, np.uint8), cv2.IMREAD_COLOR) # 背景图片
 tp_img = cv2.imdecode(np.frombuffer(tp, np.uint8), cv2.IMREAD_COLOR)  # 缺口图片

 # 对图像进行缩放
 bg_img = cv2.resize(bg_img, (0, 0), fx=scale_factor, fy=scale_factor)
 tp_img = cv2.resize(tp_img, (0, 0), fx=scale_factor, fy=scale_factor)

 # 识别图片边缘
 bg_edge = cv2.Canny(bg_img, 50, 400)
 tp_edge = cv2.Canny(tp_img, 50, 400)

 # 转换图片格式
 bg_pic = cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB)
 tp_pic = cv2.cvtColor(tp_edge, cv2.COLOR_GRAY2RGB)

 # 缺口匹配
 res = cv2.matchTemplate(bg_pic, tp_pic, cv2.TM_CCOEFF_NORMED)
 _, _, _, max_loc = cv2.minMaxLoc(res)  # 寻找最优匹配

 # 缩放坐标
 #scaled_max_loc = (max_loc[0] * scale_factor, max_loc[1] * scale_factor)

 # 绘制方框
 th, tw = tp_pic.shape[:2]
 tl = max_loc  # 左上角点的坐标
 br = (tl[0] + tw, tl[1] + th)  # 右下角点的坐标
 cv2.rectangle(bg_img, (int(tl[0]), int(tl[1])), (int(br[0]), int(br[1])), (0, 0, 255), 2)  # 绘制矩形

 # 保存至本地
 output_path = os.path.join(os.getcwd(), "output_imageX.jpg")
 cv2.imwrite(output_path, bg_img)
 tp_img_path = os.path.join(os.getcwd(), "tp_imgX.jpg")
 cv2.imwrite(tp_img_path, tp_img)

 logger.info(f"缺口的X坐标: {max_loc[0]:.4f}")

 # 返回缺口的X坐标
 return max_loc[0] - 2.5

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
        logger.debug(f"请求session: {session}")
        try:
            # 验证码获取
            clientUUID = generate_client_uuid()
            logger.info(f"clientUUID：{clientUUID}")
            captcha_resp = session.post(
                f"{BASE_url}/code/create",
                headers=headers,
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": clientUUID,
                    "ts": round(time.time() * 1000)
                }
            )
            captcha_resp.raise_for_status()
            captcha_data = captcha_resp.json()

            # 添加关键字段检查
            if 'data' not in captcha_data or 'repData' not in captcha_data['data']:
                raise ValueError("验证码响应数据结构异常")
            # 图像识别
            pos = getImgPos(
                captcha_resp['data']['repData']['originalImageBase64'],
                captcha_resp['data']['repData']['jigsawImageBase64'],
                scale_factor = 400 / 310
            )
            posStr = '{"x":' + str(pos * (310 / 400)) + ',"y":5}'
            logger.debug(f"posStr验证码接口返回: {json.dumps(posStr, indent=2)}")
            encrypted_pos = aes_encrypt(
                posStr,
                captcha_resp['data']['repData']['secretKey']
            )
            logger.info(f"encrypted_pos：{encrypted_pos}")
            # 验证码校验
            check_resp = session.post(
                f"{BASE_url}/code/check",
                headers=headers,
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": clientUUID,
                    "pointJson": encrypted_pos,
                    "token": captcha_resp['data']['repData']['token'],
                    "ts": int(time.time()*1000)
                }
            ).json()
            logger.debug(f"验证码校验响应: {check_resp}")
            # Token获取
            token_resp = session.post(
                f"{BASE_url}/auth/custom/token",
                headers=headers,
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
            logger.debug(f"获取 Token 响应: {token_resp}")
            
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
