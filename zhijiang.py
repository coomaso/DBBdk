import requests
import json
import os
import time
from loguru import logger
from datetime import datetime, timedelta
from collections import defaultdict

# 配置参数
max_attempts = 10
# 支持多个人员查询
names = ["唐丽", "周民锋", "朱陈超", "黄正明"]
BASE_url = "http://106.15.60.27:33333"
login_url = "http://106.15.60.27:33333/laboratt/attendance/page"
wexinqq_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fc744023-75ec-420d-95d1-d9c896117c29"

# 企业微信消息长度限制 (4096字符)
MAX_MESSAGE_LENGTH = 2000  # 保留一些空间

# 工作时长阈值 (小时)
WORK_DURATION_THRESHOLD = 4

headers = {
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
        # 检查内容长度
        if len(content) > MAX_MESSAGE_LENGTH:
            logger.warning(f"消息长度 {len(content)} 超过限制 ({MAX_MESSAGE_LENGTH})，将被截断")
            content = content[:MAX_MESSAGE_LENGTH] + "\n\n...（内容过长被截断）"
        
        response = requests.post(
            wexinqq_url,
            json={'msgtype': 'markdown', 'markdown': {'content': content}},
            timeout=10
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

def send_paginated_messages(messages):
    """分页发送消息，避免超过长度限制"""
    if not messages:
        return False
    
    # 计算每条消息的平均长度
    total_length = sum(len(msg) for msg in messages)
    if messages:
        avg_length = total_length / len(messages)
    else:
        avg_length = 0
    
    # 计算每批可以包含多少条消息
    if avg_length > 0:
        batch_size = max(1, int(MAX_MESSAGE_LENGTH / avg_length))
    else:
        batch_size = 5  # 默认每批5条
    
    logger.info(f"平均每条消息长度: {avg_length:.0f}, 每批发送 {batch_size} 条记录")
    
    # 分批发送
    all_success = True
    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]
        content = "\n\n".join(batch)
        
        # 添加分页信息
        total_pages = (len(messages) + batch_size - 1) // batch_size
        current_page = i // batch_size + 1
        page_info = f"# 📋 考勤记录通知 ({current_page}/{total_pages})\n\n"
        
        # 发送当前批次
        logger.info(f"发送第 {current_page}/{total_pages} 批消息 ({len(batch)}条记录)")
        if not send_wexinqq_md(page_info + content):
            all_success = False
            logger.error(f"第 {current_page} 批消息发送失败")
        
        # 批次间延迟
        time.sleep(1)
    
    return all_success

# ================== 数据监控 ==================
def load_existing_ids():
    """加载已记录的ID集合"""
    try:
        if os.path.exists('zjids.json'):
            with open('zjids.json') as f:
                ids = json.load(f)
                logger.info(f"成功加载 {len(ids)} 条历史记录ID")
                return set(ids)
        else:
            logger.warning("未找到zjids.json文件，将创建新文件")
            return set()
    except json.JSONDecodeError:
        logger.error("zjids.json文件格式错误，将重新创建")
        return set()

def save_new_ids(ids):
    """保存新的ID集合"""
    try:
        with open('zjids.json', 'w') as f:
            json.dump(list(ids), f)
        logger.info(f"成功保存{len(ids)}条记录ID到zjids.json")
    except Exception as e:
        logger.error(f"保存ID集合失败: {str(e)}")

def fetch_records_for_name(name):
    """获取单个名字的第一页数据"""
    try:
        # 构建查询URL
        url = f"{login_url}?page=1&limit=10&name={name}&orderByField=verifyTime&isAsc=false"
        logger.debug(f"请求URL: {url}")
        
        response = requests.get(url, headers=headers, timeout=60)
        logger.info(f"请求 {name} 的考勤记录, 状态码: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"请求失败: {response.text}")
            return []

        json_data = response.json()

        # 兼容处理不同结构
        if "data" in json_data and isinstance(json_data["data"], dict):
            records = json_data["data"].get("records", [])
        elif "records" in json_data and isinstance(json_data["records"], list):
            records = json_data["records"]
        else:
            logger.error(f"响应格式异常: {json_data}")
            return []

        logger.info(f"获取到 {name} 的 {len(records)} 条记录")
        return records
        
    except Exception as e:
        logger.error(f"获取数据失败: {e}")
        return []

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

def process_records(records):
    """处理记录，添加北京时间"""
    processed_records = []
    
    for record in records:
        timestamp = record.get('verifyTime', 0) / 1000
        if timestamp:
            utc_time = datetime.utcfromtimestamp(timestamp)
            beijing_time = utc_time + timedelta(hours=8)
            record['beijing_time'] = beijing_time
            record['date_key'] = beijing_time.date().isoformat()
        else:
            record['beijing_time'] = None
            record['date_key'] = 'unknown'
        
        processed_records.append(record)
    
    return processed_records

def calculate_daily_work_durations(processed_records):
    """计算每个人每天的工作时长"""
    daily_work_durations = {}
    daily_records = defaultdict(lambda: defaultdict(list))
    
    # 按姓名和日期分组记录
    for record in processed_records:
        name = record.get('name', '未知')
        date_key = record.get('date_key')
        status = record.get('inOrOut', 'unknown')
        beijing_time = record.get('beijing_time')
        
        if name != '未知' and date_key != 'unknown' and beijing_time:
            daily_records[(name, date_key)][status].append(beijing_time)
    
    # 计算每天的工作时长
    for (name, date_key), records_by_status in daily_records.items():
        in_times = records_by_status.get('in', [])
        out_times = records_by_status.get('out', [])
        
        if in_times and out_times:
            # 找到最早的进入时间
            earliest_in = min(in_times)
            # 找到最晚的离开时间
            latest_out = max(out_times)
            
            # 确保离开时间在进入时间之后
            if latest_out > earliest_in:
                # 计算工作时长（小时）
                work_duration = (latest_out - earliest_in).total_seconds() / 3600
                
                # 记录工作时长
                daily_work_durations[(name, date_key)] = work_duration
                
                logger.info(f"{name} 在 {date_key} 的工作时长: {work_duration:.2f}小时")
                logger.info(f"  最早进入: {earliest_in.strftime('%H:%M:%S')}")
                logger.info(f"  最晚离开: {latest_out.strftime('%H:%M:%S')}")
            else:
                logger.warning(f"{name} 在 {date_key} 的离开时间早于进入时间，不计算工作时长")
        else:
            logger.info(f"{name} 在 {date_key} 缺少进出记录，无法计算工作时长")
    
    return daily_work_durations

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
            
            # 处理记录，添加北京时间
            processed_records = process_records(new_records)
            
            # 计算每日工作时长
            daily_work_durations = calculate_daily_work_durations(processed_records)
            
            messages = []
            warning_dates = []
            warnings_by_date = {}
            
            # 检查哪些日期的工作时长不足
            for (name, date_key), duration in daily_work_durations.items():
                if duration < WORK_DURATION_THRESHOLD:
                    warning_dates.append((name, date_key))
                    warnings_by_date[(name, date_key)] = {
                        'duration': duration,
                        'name': name,
                        'date': date_key
                    }
                    logger.warning(f"{name} 在 {date_key} 的工作时长不足: {duration:.2f}小时 (< {WORK_DURATION_THRESHOLD}小时)")
            
            # 为每条记录创建消息
            for record in processed_records:
                beijing_time = record.get('beijing_time')
                time_str = beijing_time.strftime('%Y-%m-%d %H:%M:%S') if beijing_time else "未知时间"
                
                # 获取项目名称
                project_name = record.get('engName', '未知项目')
                if not project_name or project_name == 'null':
                    project_name = record.get('projectName', '未知项目')
                
                # 获取进出状态
                status = record.get('inOrOut', '未知')
                status_text = "进入" if status == 'in' else "离开"
                status_color = "info" if status == 'in' else "warning"
                
                # 创建消息
                message = (
                    f"## 🎉 新考勤记录\n"
                    f"> **项目名称**: {project_name}\n"
                    f"> **姓名**: {record.get('name', '未知')}\n"
                    f"> **岗位**: {record.get('jobName', '未知')}\n"
                    f"> **时间**: <font color=\"info\">{time_str}</font>\n"
                    f"> **状态**: <font color=\"{status_color}\">{status_text}</font>\n"
                )
                
                # 对于离开记录，检查是否有关联的日期需要警告
                name = record.get('name', '未知')
                date_key = record.get('date_key')
                
                # 只有在离开记录且该日期有工作时长计算时才显示
                if status == 'out' and name != '未知' and date_key != 'unknown' and beijing_time:
                    if (name, date_key) in warnings_by_date:
                        duration = warnings_by_date[(name, date_key)]['duration']
                        message += f"> **当天工作时长**: {duration:.2f}小时\n"
                        message += f"> **警告**: <font color=\"warning\">工作时长不足{WORK_DURATION_THRESHOLD}小时！</font>\n"
                    elif (name, date_key) in daily_work_durations:
                        # 如果工作时长正常，也可以显示（可选）
                        duration = daily_work_durations.get((name, date_key))
                        if duration:
                            message += f"> **当天工作时长**: {duration:.2f}小时\n"
                
                messages.append(message)
            
            # 添加总标题
            summary = f"# 📢 发现 {len(new_records)} 条新考勤记录\n"
            if warning_dates:
                summary += f"## ⚠️ 其中有 {len(warning_dates)} 天的工作时长不足{WORK_DURATION_THRESHOLD}小时\n"
                # 按姓名分组显示警告
                warnings_by_name = defaultdict(list)
                for name, date_key in warning_dates:
                    duration = daily_work_durations.get((name, date_key), 0)
                    warnings_by_name[name].append((date_key, duration))
                
                for name, date_list in warnings_by_name.items():
                    for date_key, duration in date_list:
                        summary += f"> **{name}** 在 **{date_key}** 的工作时长: {duration:.2f}小时\n"
                summary += "\n"
            
            # 分页发送消息
            message_list = [summary] + messages
            send_success = send_paginated_messages(message_list)
            
            # 通知发送成功后才保存ID
            if send_success:
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
        import traceback
        logger.error(traceback.format_exc())
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
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    # 配置日志
    logger.add(
        "attendance_monitor.log", 
        rotation="10 MB", 
        retention="7 days", 
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO"
    )
    
    logger.info("======= 考勤监控程序启动 =======")
    logger.info(f"监控人员: {', '.join(names)}")
    logger.info(f"工作时长阈值: {WORK_DURATION_THRESHOLD}小时")
    start_time = time.time()
    
    main()
    
    duration = time.time() - start_time
    logger.info(f"程序运行完成，耗时: {duration:.2f}秒")
    logger.info("=" * 50)
