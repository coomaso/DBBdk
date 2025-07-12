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
idCardSign = "MDoCAQEwEgIBATAKBggqgRzPVQFoAQoBAQMhALC5L1lSMTEQLmI33J1qUDVhRVwTyt%2Be%2B27ntIC3g2Wb"
BASE_url = "http://106.15.60.27:33333"
login_url = "http://106.15.60.27:33333/laboratt/attendance/page"
wexinqq_url = os.environ["QYWX_URL"]

headers = {
 "Host": "zhcjsmz.sanxiacloud.com",
 "Connection": "keep-alive",
 "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="114"',
 "Accept": "*/*",
 "Content-Type": "application/json;charset=UTF-8",
 "sec-ch-ua-mobile": "?0",
 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.289 Safari/537.36",
 "sec-ch-ua-platform": '"Windows"',
 "Origin": "http://106.15.60.27:33333",
 "Referer": "http://106.15.60.27:33333/login/",
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
           (current_time - token_data['obtained_time'] < 6 * 3600)

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
    request_headers = headers.copy()
    request_headers["Authorization"] = f"bearer {access_token}"
    
    all_records = []
    page = 1
    while True:
        try:
            response = requests.get(
                f"{login_url}?page={page}&limit=10&idCardSign={idCardSign}&orderByField=verifyTime&isAsc=false",
                # headers=request_headers
            )
            logger.info(f"请求原文: {response.text}")
            logger.info(f"请求状态码: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"请求失败: {response.text}")
                break

            json_data = response.json()

            # 兼容处理不同结构
            if "data" in json_data and isinstance(json_data["data"], dict):
                records = json_data["data"].get("records", [])
            elif "records" in json_data and isinstance(json_data["records"], list):
                records = json_data["records"]
            else:
                logger.error(f"响应格式异常: {json_data}")
                break

            if not records:
                logger.info("没有更多记录了")
                break

            all_records.extend(records)
            page += 1
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
            # 将时间戳转换为UTC时间
            utc_time = datetime.utcfromtimestamp(timestamp)
            # 添加8小时偏移，转为北京时间
            beijing_time = utc_time + timedelta(hours=8)
            messages.append(
                f"## 🎉 **新考勤记录** 🎉\n"
                f"> **项目名称**: {r.get('engName', '未知')}\n"
                f"> **姓名**: {r.get('name', '未知')}\n"
                f"> **岗位**: {r.get('jobName', '未知')}\n"
                f"> **时间**: <font color=\"info\">{beijing_time.strftime('%Y-%m-%d %H:%M:%S')}</font> (北京时间)\n"
                f"> **状态**: <font color=\"warning\">{'进入' if r.get('inOrOut') == 'in' else '离开'}</font>\n"
            )
        send_result = send_wexinqq_md("\n\n".join(messages))
        # save_new_ids(existing_ids.union(current_ids))
        if send_result.get('errcode') == 0:
            save_new_ids(existing_ids.union(current_ids))
            return True
        logger.error(f"消息发送失败: {send_result}")
    return False

# ================== Token获取主流程 ==================
def refresh_token():
    for attempt in range(1, max_attempts+1):
        logger.info(f"Token获取尝试第{attempt}次")
        session = requests.Session()
        response = session.get("http://106.15.60.27:33333/login/#/login", headers=headers)
        
        # 解析 Cookie
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
        session.cookies.update(cookies_dict)
     
        try:
            # ========== 验证码请求 ==========
            clientUUID = generate_client_uuid() 
            current_timestamp_milliseconds = round(time.time() * 1000)
            data = {
                "captchaType": "blockPuzzle",
                "clientUid": clientUUID,
                "ts": current_timestamp_milliseconds
            }       
            captcha_resp = session.post(
                f"{BASE_url}/code/create",
                headers=headers,
                json=data,
                timeout=15
            )
            # 先检查状态码
            if captcha_resp.status_code != 200:
                logger.error(f"API 请求失败，状态码: {captcha_resp.status_code}, 响应内容: {captcha_resp.text}")
                raise ValueError("API 请求失败，请检查请求参数或服务器状态")

            # 解析JSON
            try:
                captcha_data = captcha_resp.json()
            except json.JSONDecodeError as e:
                logger.error(f"验证码响应非JSON: {captcha_resp.text}, 错误信息: {str(e)}")
                raise ValueError("API 返回的不是有效的 JSON 数据")
                continue

            # 确保 captcha_data 不是 None
            if not captcha_data:
                logger.error(f"API 返回空数据，响应内容: {captcha_resp.text}")
                raise ValueError("API 返回的数据为空")
            
            # 确保 captcha_data 结构正确
            if "data" not in captcha_data or "repData" not in captcha_data["data"]:
                logger.error(f"API 返回的数据格式不正确: {captcha_data}")
                raise ValueError("API 返回的数据缺少 'data' 或 'repData' 字段")

            # ========== 验证码识别 ==========
            # 获取原始坐标（无需缩放计算）
            pos = getImgPos(
                captcha_data['data']['repData']['originalImageBase64'],
                captcha_data['data']['repData']['jigsawImageBase64'],
                scale_factor=400 / 310
            )
            posStr =  '{"x":' + str(pos * (310 / 400)) + ',"y":5}'
            
            # ========== 加密参数生成 ==========
            encrypted_pos = aes_encrypt(
                posStr,
                captcha_data['data']['repData']['secretKey']
            )
            logger.info(f"加密参数 {encrypted_pos}")
            # ========== 验证码校验 ==========
            check_resp = session.post(
                f"{BASE_url}/code/check",
                json={
                    "captchaType": "blockPuzzle",
                    "clientUid": clientUUID,
                    "pointJson": encrypted_pos,
                    "token": captcha_data['data']['repData']['token'],
                    "ts": current_timestamp_milliseconds
                },
                headers=headers,
                timeout=15
            )
           # 校验结果检查（修复变量引用顺序）
            try:
                check_data = check_resp.json()
                logger.debug(f"验证码校验响应: {check_data}")  # 添加调试日志
                
                # 根据实际接口响应结构调整判断条件
                if check_data.get('code') != 0 or not check_data.get('data', {}).get('repData', {}).get('result'):
                    logger.error(f"验证失败: {check_data}")
                    raise ValueError("验证码校验未通过")
            except json.JSONDecodeError:
                logger.error(f"校验响应非JSON: {check_resp.text}")
                continue

            # ========== Token请求 ==========
            captcha = aes_encrypt(captcha_data['data']['repData']['token'] + '---' + posStr, captcha_data['data']['repData']['secretKey'])
            logger.info(f"加密后的 captcha: {captcha}")
            token_resp = session.post(
                f"{BASE_url}/auth/custom/token",
                params={
                    "username": "13487283013",
                    "grant_type": "password",
                    "scope": "server",
                    "code": captcha,
                    "randomStr": "blockPuzzle"
                },
                json={"sskjPassword": "2giTy1DTppbddyVBc0F6gMdSpT583XjDyJJxME2ocJ4="},
                headers=headers,
                timeout=15
            )
            
            # Token结果处理
            try:
                token_data = token_resp.json()
                logger.info(f"返回 JSON: {token_data}")  
                if 'access_token' in token_data:
                    save_token(token_data['access_token'], token_data.get('expires_in', 7200))
                    return token_data['access_token']
                else:
                    logger.error(f"Token获取失败: {token_data}")
            except json.JSONDecodeError:
                logger.error(f"Token响应非JSON: {token_resp.text}")
            
        except Exception as e:
            logger.error(f"尝试{attempt}失败详情:")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"错误信息: {str(e)}")
            time.sleep(random.uniform(1, 5))
    
    raise Exception("无法获取有效Token")


# ================== 主循环 ==================
def main():
    try:
        # Token有效性检查
        # token_data = load_token()
        # if not is_token_valid(token_data):
        #     logger.info("Token无效或已过期，需要刷新")
        #     access_token = refresh_token()
        # else:
        #     access_token = token_data['access_token']
        
        # 数据检查
        # if check_new_records(access_token):
        #     logger.success("发现新记录并成功通知")
        # else:
        #     logger.info("未发现新记录")
        
        # 一次性执行后结束程序，不再循环
        # logger.info("执行完毕，程序结束")
    
    except KeyboardInterrupt:
        logger.info("程序已手动终止")
    except Exception as e:
        logger.error(f"主循环异常: {str(e)}")

if __name__ == "__main__":
    main()
