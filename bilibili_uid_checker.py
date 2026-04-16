"""
Bilibili UID 检查器 (多线程版本)
连接本地 Chrome 浏览器，多线程随机生成x位UID访问B站用户空间，
筛选出「乱码英文用户名 + 0级」的账号并记录到 result.txt。
"""

import random
import re
import time
import os
import threading
import queue
import subprocess
import sys
from DrissionPage import ChromiumPage, ChromiumOptions


#======================== 配置 ========================
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result.txt")

#延迟时间范围
MIN_DELAY = 2
MAX_DELAY = 5

#线程数
THREAD_COUNT = 10

#UID前缀
UID_PREFIX = 77
#前缀后面的UID数字范围
range_min = 0
range_max = 100000


pattern = r'^(?=.*[a-z])(?=.*\d).+$'

DEBUGGING_PORTS = list(range(9222, 9222 + THREAD_COUNT))

file_lock = threading.Lock()
print_lock = threading.Lock()

#常见英文子串，如果用户名里包含这些，说明可能是真名
COMMON_SUBSTRINGS = [
    "the", "ing", "tion", "ment", "able", "ness", "ful", "less",
    "game", "love", "cool", "star", "fire", "dark", "blue", "king",
    "play", "hero", "wolf", "fox", "cat", "dog", "sky", "moon",
    "sun", "ice", "war", "pro", "max", "boy", "girl", "man",
    "fan", "god", "ace", "top", "big", "red", "hot", "old",
    "new", "one", "two", "day", "way", "eye", "her", "his",
    "you", "not", "all", "can", "out", "use", "how", "its",
    "may", "did", "get", "has", "him", "see", "now", "come",
    "than", "like", "just", "over", "know", "back", "only",
    "good", "some", "time", "very", "when", "with", "make",
    "hand", "high", "keep", "last", "long", "much", "own",
    "say", "she", "too", "any", "same", "tell", "each",
    "bilibili", "bili", "video", "anime", "music", "live",
    "chen", "wang", "zhang", "yang", "huang", "zhao", "zhou",
    "chun", "xiao", "ming", "hong", "feng", "jing", "ying",
    "qing", "long", "ping", "ling", "dong", "song", "tang",
]

VOWELS = set("aeiou")


def is_gibberish_name(name: str) -> bool:
    if not re.fullmatch(r"[a-z0-9]+", name):
        return False
        
    if not re.fullmatch(pattern, name):
        return False
        
    if re.search(r'\d{3}', name):
        return False

    if not (6 <= len(name) <= 12):
        return False

    consonant_count = sum(1 for ch in name if ch not in VOWELS)
    if consonant_count / len(name) <= 0.60:
        return False

    name_lower = name.lower()
    for sub in COMMON_SUBSTRINGS:
        if sub in name_lower:
            return False

    return True


#======================== 等级提取 ========================
def get_user_level(page) -> int:
    try:
        level_elem = page.ele("css:i.level-icon", timeout=5)
        if level_elem:
            cls = level_elem.attr("class") or ""
            match = re.search(r"user_level_(\d)", cls)
            if match:
                return int(match.group(1))

        level_elem = page.ele("css:i[class*='user_level_']", timeout=3)
        if level_elem:
            cls = level_elem.attr("class") or ""
            match = re.search(r"user_level_(\d)", cls)
            if match:
                return int(match.group(1))

        return -1
    except Exception:
        return -1


#======================== 用户名提取 ========================
def get_username(page) -> str:
    try:
        name_elem = page.ele("css:div.nickname", timeout=5)
        if name_elem:
            return name_elem.text.strip()

        name_elem = page.ele("css:[class*='nickname']", timeout=3)
        if name_elem:
            return name_elem.text.strip()

        return ""
    except Exception:
        return ""


#======================== 线程工作函数 ========================
def worker(thread_id: int, port: int, uid_queue: queue.Queue, stats: dict):
    try:
        co = ChromiumOptions()
        co.set_local_port(port)
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-blink-features=AutomationControlled')
        page = ChromiumPage(co)
        with print_lock:
            print(f"[线程 {thread_id:2d}] 已连接 Chrome (端口 {port})")
    except Exception as e:
        with print_lock:
            print(f"[线程 {thread_id:2d}] 连接 Chrome 失败 (端口 {port}): {e}")
        return

    local_checked = 0
    local_found = 0

    while True:
        try:
            uid = uid_queue.get(timeout=5)
        except queue.Empty:
            break

        url = f"https://space.bilibili.com/{uid}"

        try:
            page.get(url)
            time.sleep(1.5)

            username = get_username(page)
            level = get_user_level(page)

            local_checked += 1

            if not username:
                with print_lock:
                    print(f"[线程 {thread_id:2d}] UID {uid} — 无法获取用户名，跳过")
            elif level == -1:
                with print_lock:
                    print(f"[线程 {thread_id:2d}] UID {uid} — 无法获取等级，跳过")
            else:
                is_gibberish = is_gibberish_name(username)
                is_level_0 = (level == 0)

                if is_gibberish and is_level_0:
                    local_found += 1
                    with file_lock:
                        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                            f.write(f"UID: {uid} | 用户名: {username}\n")
                    
                    with print_lock:
                        stats['found'] += 1
                        print(f"[线程 {thread_id:2d}] UID {uid} — 用户名: {username} | 等级: Lv{level} | 命中！累计: {stats['found']} 个")
                else:
                    with print_lock:
                        stats['checked'] += 1
                        if stats['checked'] % 100 == 0:
                            print(f"[线程 {thread_id:2d}] 进度: {stats['checked']} | 当前 UID: {uid}")

        except Exception as e:
            local_checked += 1
            with print_lock:
                stats['checked'] += 1
                if "ERR_CONNECTION" not in str(e):
                    print(f"[线程 {thread_id:2d}] UID {uid} — 访问出错: {str(e)[:50]}")

        uid_queue.task_done()

        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        time.sleep(delay)

    with print_lock:
        print(f"[线程 {thread_id:2d}] 完成，检查了 {local_checked} 个 UID，命中 {local_found} 个")


#======================== Chrome 启动管理 ========================
def stop_chrome_instances():
    """停止所有Chrome实例"""
    print("\n正在停止所有Chrome实例...")
    try:
        subprocess.run(["pkill", "-f", "Google Chrome.*remote-debugging-port"], check=False)
        print("Chrome实例已停止")
    except Exception as e:
        print(f"停止Chrome实例时出错: {e}")


#======================== 主逻辑 ========================
def main():
    print("=" * 60)
    print("   Bilibili UID 检查器 — 多线程版本")
    print("=" * 60)

    print(f"\n生成 UID 列表... (前缀: {UID_PREFIX})")
    uid_list = []
    
    width = len(str(range_max)) - 1
    
    for remaining in range(range_min, range_max):
        uid = int(f"{UID_PREFIX}{remaining:0{width}d}")
        uid_list.append(uid)
    
    print(f"已生成 {len(uid_list):,} 个待检查的 UID")

    uid_queue = queue.Queue()
    for uid in uid_list:
        uid_queue.put(uid)

    stats = {
        'checked': 0,
        'found': 0
    }

    print(f"\n启动 {THREAD_COUNT} 个线程开始检查...")
    print(f"结果保存至: {OUTPUT_FILE}")
    print("-" * 60)

    threads = []
    for i in range(THREAD_COUNT):
        t = threading.Thread(
            target=worker,
            args=(i + 1, DEBUGGING_PORTS[i], uid_queue, stats)
        )
        t.daemon = True
        t.start()
        threads.append(t)
        time.sleep(0.1)

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print(f"\n\n{'=' * 60}")
        print(f"手动停止")
        print(f"共检查: {stats['checked']:,} 个 UID")
        print(f"命中数: {stats['found']} 个")
        print(f"结果文件: {OUTPUT_FILE}")
        print(f"{'=' * 60}")
        
        if chrome_processes:
            response = input("\n是否停止所有Chrome实例？(y/n): ").strip().lower()
            if response == 'y':
                stop_chrome_instances()
        return

    print(f"\n{'=' * 60}")
    print(f"全部完成！")
    print(f"共检查: {stats['checked']:,} 个 UID")
    print(f"命中数: {stats['found']} 个")
    print(f"结果文件: {OUTPUT_FILE}")
    print(f"{'=' * 60}")

    if chrome_processes:
        response = input("\n是否停止所有Chrome实例？(y/n): ").strip().lower()
        if response == 'y':
            stop_chrome_instances()


if __name__ == "__main__":
    main()