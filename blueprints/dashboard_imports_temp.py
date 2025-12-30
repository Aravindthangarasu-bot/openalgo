from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from database.auth_db import get_auth_token, get_api_key_for_tradingview
from database.settings_db import get_analyze_mode
from services.funds_service import get_funds
from services.quotes_service import get_multiquotes
from utils.session import check_session_validity
from utils.logging import get_logger
