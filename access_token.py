import requests
import json
import os
from loguru import logger
from datetime import datetime, timedelta

# 配置参数
max_attempts = 10
# 支持多个人员查询
names = ["代碧波", "周民锋"]
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

# ================== 通知发送 ==================
def send_wexinqq_md(content):
    """发送Markdown消息到企业微信"""
    try:
        response = requests.post(
            wexinqq_url,
            json={'msgtype': 'markdown', 'markdown': {'content': content}}
        )
        result = response.json()
        if result.get('errcode') == 0:
            logger.success("企业微信通知发送成功")
            return True
        else:
            logger.error(f"企业微信通知发送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"发送企业微信通知时出错: {str(e)}")
        return False

# ================== 数据监控 ==================
def load_existing_ids():
    """加载已记录的ID集合"""
    try:
        with open('ids.json') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("未找到ids.json文件或文件格式错误，将创建新文件")
        return set()

def save_new_ids(ids):
    """保存新的ID集合"""
    try:
        with open('ids.json', 'w') as f:
            json.dump(list(ids), f)
        logger.info(f"成功保存{len(ids)}条记录ID到ids.json")
    except Exception as e:
        logger.error(f"保存ID集合失败: {str(e)}")

def fetch_records_for_name(name):
    """获取单个名字的所有分页数据"""
    records = []
    page = 1
    while True:
        try:
            # 构建查询URL
            url = f"{login_url}?page={page}&limit=100&name={name}&orderByField=verifyTime&isAsc=false"
            logger.debug(f"请求URL: {url}")
            
            response = requests.get(url, headers=headers)
            logger.info(f"请求 {name} 的考勤记录, 页码: {page}, 状态码: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"请求失败: {response.text}")
                break

            json_data = response.json()
            logger.debug(f"响应数据: {json_data}")

            # 兼容处理不同结构
            if "data" in json_data and isinstance(json_data["data"], dict):
                page_records = json_data["data"].get("records", [])
            elif "records" in json_data and isinstance(json_data["records"], list):
                page_records = json_data["records"]
            else:
                logger.error(f"响应格式异常: {json_data}")
                break

            if not page_records:
                logger.info(f"名字 {name} 的第 {page} 页没有更多记录了")
                break

            records.extend(page_records)
            logger.info(f"第 {page} 页获取到 {len(page_records)} 条记录")
            page += 1
            
            # 添加延迟避免请求过快
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"获取数据失败: {e}")
            break
    
    logger.info(f"总共获取到 {len(records)} 条 {name} 的记录")
    return records

def fetch_all_records():
    """获取所有名字的所有记录"""
    all_records = []
    for name in names:
        logger.info(f"开始查询 {name} 的考勤记录")
        records = fetch_records_for_name(name)
        all_records.extend(records)
        logger.success(f"查询到 {name} 的 {len(records)} 条记录")
    
    # 按时间排序 (从新到旧)
    all_records.sort(key=lambda x: x.get('verifyTime', 0), reverse=True)
    return all_records

def check_new_records():
    """检查新记录并发送通知"""
    try:
        existing_ids = load_existing_ids()
        logger.info(f"已加载 {len(existing_ids)} 条历史记录ID")
        
        current_ids = set()
        new_records = []
        
        records = fetch_all_records()
        logger.info(f"总共查询到 {len(records)} 条记录")
        
        # 检查新记录
        for record in records:
            record_id = record.get('id')
            if not record_id:
                continue
                
            current_ids.add(record_id)
            if record_id not in existing_ids:
                new_records.append(record)
        
        if new_records:
            logger.success(f"发现 {len(new_records)} 条新记录")
            
            # 按时间排序 (从旧到新，这样通知中先显示最早的记录)
            new_records.sort(key=lambda x: x.get('verifyTime', 0))
            
            messages = []
            for r in new_records:
                timestamp = r.get('verifyTime', 0) / 1000
                # 将时间戳转换为UTC时间
                utc_time = datetime.utcfromtimestamp(timestamp)
                # 添加8小时偏移，转为北京时间
                beijing_time = utc_time + timedelta(hours=8)
                
                # 获取项目名称，如果不存在则使用默认值
                project_name = r.get('engName', '未知项目')
                if not project_name or project_name == 'null':
                    project_name = r.get('projectName', '未知项目')
                    
                # 获取进出状态
                status = r.get('inOrOut', '未知')
                status_text = "进入" if status == 'in' else "离开"
                status_color = "info" if status == 'in' else "warning"
                
                messages.append(
                    f"## 🎉 **新考勤记录** 🎉\n"
                    f"> **项目名称**: {project_name}\n"
                    f"> **姓名**: {r.get('name', '未知')}\n"
                    f"> **岗位**: {r.get('jobName', '未知')}\n"
                    f"> **时间**: <font color=\"info\">{beijing_time.strftime('%Y-%m-%d %H:%M:%S')}</font> (北京时间)\n"
                    f"> **状态**: <font color=\"{status_color}\">{status_text}</font>\n"
                )
            
            # 添加标题和总结信息
            content = f"# 📢 发现 {len(new_records)} 条新考勤记录\n\n" + "\n\n".join(messages)
            
            # 发送通知
            if send_wexinqq_md(content):
                # 通知发送成功后才保存ID
                save_new_ids(existing_ids.union(current_ids))
                return True
            else:
                logger.error("通知发送失败，不更新记录ID")
                return False
        else:
            logger.info("未发现新记录")
            return False
            
    except Exception as e:
        logger.error(f"检查新记录时出错: {str(e)}")
        return False

# ================== 主循环 ==================
def main():
    try:
        # 数据检查
        if check_new_records():
            logger.success("发现新记录并成功通知")
        else:
            logger.info("未发现新记录")
        
        # 一次性执行后结束程序，不再循环
        logger.info("执行完毕，程序结束")
    
    except KeyboardInterrupt:
        logger.info("程序已手动终止")
    except Exception as e:
        logger.error(f"主循环异常: {str(e)}")

if __name__ == "__main__":
    import time
    logger.add("attendance_monitor.log", rotation="10 MB", retention="7 days")
    logger.info("======= 考勤监控程序启动 =======")
    main()
