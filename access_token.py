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

base_url = "https://zhcjsmz.sc.yichang.gov.cn"

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
}

# 加密函数
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

# 初始化 UUID
def generate_client_uuid():
    s = []
    hex_digits = "0123456789abcdef"
    for i in range(36):
        s.append(hex_digits[random.randint(0, 15)])
    s[14] = "4"  # time_hi_and_version字段的12-15位设置为0010
    s[19] = hex_digits[(int(s[19], 16) & 0x3) | 0x8]  # clock_seq_hi_and_reserved字段的6-7位设置为01
    s[8] = s[13] = s[18] = s[23] = "-"
    slider = 'slider' + '-' + ''.join(s)
    return slider

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

# 接受原始图像的Base64编码字符串和新的宽度作为参数，返回调整大小后的图像的Base64编码字符串
def resize_image(base64_string, new_width):
    # 将Base64字符串解码为字节数据
    image_data = base64.b64decode(base64_string)

    # 将字节数据转换为图像对象
    image = Image.open(io.BytesIO(image_data))

    # 确保图像的模式是RGB
    if image.mode != 'RGB':
        image = image.convert('RGB')

    # 计算高度以保持宽高比
    original_width, original_height = image.size
    new_height = int((new_width / original_width) * original_height)

    # 调整图像大小
    resized_image = image.resize((new_width, new_height))

    # 将调整大小后的图像转换为Base64字符串
    buffered = io.BytesIO()
    resized_image.save(buffered, format="JPEG")
    resized_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return resized_base64

# Function to read the existing access token and timestamp from access_token.json
def read_access_token():
    try:
        with open('../access_token.json', 'r') as json_file:
            data = json.load(json_file)
            return data.get('access_token'), data.get('timestamp', 0)
    except FileNotFoundError:
        return None, 0


# Read the existing access token and timestamp
existing_access_token, existing_timestamp = read_access_token()

# Check if the access token is not present or if the timestamp difference is greater than 6 hours
if not existing_access_token or (time.time() - existing_timestamp) > (6 * 60 * 60):
    # 创建一个对话
    session = requests.session()
    response = session.get("https://zhcjsmz.sc.yichang.gov.cn/login/#/login", headers=headers)

    # 随机生成 UUID
    clientUUID = generate_client_uuid()

    # 获取当前时间戳
    current_timestamp_milliseconds = round(time.time() * 1000)

    data = {
        "captchaType": "blockPuzzle",
        "clientUid": clientUUID,
        "ts": current_timestamp_milliseconds
    }

    # 获取图片
    response = session.post(f"{base_url}/code/create", headers=headers, json=data)
    response_data = response.json()  # Use response.json() to parse JSON
    logger.info(f"返回response.cookies: {response.cookies.get_dict()}")
    # 提取值
    secret_key = response_data["data"]["repData"]["secretKey"]
    token = response_data["data"]["repData"]["token"]

    bg_img_base64 = response_data["data"]["repData"]["originalImageBase64"]
    hk_img_base64 = response_data["data"]["repData"]["jigsawImageBase64"]

    pos = getImgPos(bg_img_base64, hk_img_base64, scale_factor=400/310)

    formatted_pos = pos

    logger.info(f"pos文本: {formatted_pos}")

    posStr = '{"x":' + str(formatted_pos*(310/400)) + ',"y":5}'
    logger.info(f"posStr文本: {posStr}")
    pointJson = aes_encrypt(posStr, secret_key)

    logger.info(f"加密后的文本pointJson_text: {pointJson}")

    pverdat = json.dumps({
        "captchaType": "blockPuzzle",
        "clientUid": clientUUID,
        "pointJson": pointJson,
        "token": token,
        "ts": current_timestamp_milliseconds
    })
    logger.info(f"图片检查传参: {pverdat}")

    htm = session.post(f"{base_url}/code/check", json=json.loads(pverdat), headers=headers)  # Use json parameter
    logger.info(f"返回htm_text: {htm.text}")
    logger.info(f"返回htm.cookies: {htm.cookies.get_dict()}")
    
    if '执行成功' in htm.json()['msg']:
        #time.sleep(3 + 2 * random.random())
        
        posStr = '{"x":' + str(formatted_pos*(310/400)) + ',"y":5}'
        captcha = aes_encrypt(token + '---' + posStr, secret_key)
        logger.info(f"二次加密后的文本captcha_text: {captcha}")
        decoded_captcha = aes_decrypt(captcha, secret_key)
        logger.info(f"解码密文: {decoded_captcha}")
        
        pverdat2 = json.dumps({
            "sskjPassword": "qnsXYUm303WQpeci1uwc+w==",
            "username":"13487283013",
            "password":"13487283013",
            "grant_type":"password",
            "scope":"server",
            "code":captcha,
            "randomStr":"blockPuzzle"
        })
        logger.info(f"图片检查传参: {pverdat2}")
        headers["Authorization"] = "Basic cGlnOnBpZw=="
        headers["TENANT-ID"] = "1"
    
        #htm = session.get(f"{base_url}/auth/custom/token", data=pverdat2, headers=headers)
        pverdat3 = json.dumps({
            "sskjPassword": "2giTy1DTppbddyVBc0F6gMdSpT583XjDyJJxME2ocJ4=",
            
        })
        logger.info(f"headers: {headers}")
        htm = session.post(f"{base_url}/auth/custom/token?username=13487283013&grant_type=password&scope=server&code={captcha}&randomStr=blockPuzzle", data=pverdat3, headers=headers)
    
        try:
            logger.info(f"返回htm_text: {htm.text}")
            access_token_value = htm.json()['access_token']
            logger.info(f"返回access_token: {access_token_value}")
    
            # Create a dictionary with access_token and timestamp
            access_token_data = {
                'access_token': access_token_value,
                'timestamp': int(time.time())  # Current timestamp in seconds
            }
    
            # Write the dictionary to a local JSON file
            with open('../access_token.json', 'w') as json_file:
                json.dump(access_token_data, json_file)
    
        except KeyError:
            pass
        finally:
            session.close()
else:
    # 获取当前时间戳
    current_timestamp = time.time()

    # 将时间戳转换为日期时间对象
    current_datetime = datetime.fromtimestamp(current_timestamp)

    # 将日期时间对象格式化为字符串
    formatted_time = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
    print('无需更新access_token验证。', formatted_time)

    exit()
