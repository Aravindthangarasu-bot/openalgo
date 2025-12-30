from flask import Blueprint, jsonify, request, render_template, session
from services.telegram_listener_service import telegram_listener
from utils.session import check_session_validity
from utils.logging import get_logger
import os

logger = get_logger(__name__)
telegram_signal_bp = Blueprint('telegram_signal_bp', __name__, url_prefix='/telegram-signal')

@telegram_signal_bp.route('/config', methods=['GET', 'POST'])
@check_session_validity
def config():
    if request.method == 'GET':
        return render_template('telegram/listener_config.html', 
                             api_id=os.getenv("TELEGRAM_API_ID", ""),
                             target_channel=os.getenv("TELEGRAM_TARGET_CHANNEL", ""),
                             is_connected=telegram_listener.is_running)
    
    # Update Config
    data = request.json
    # In a real app, write to .env or DB. 
    # For this session, we set env vars in memory or print instructions.
    # Since we can't easily write .env, we'll try to update the in-memory os.environ
    # and maybe the user has to restart for full persistence if we don't write to file.
    
    if 'api_id' in data:
        os.environ['TELEGRAM_API_ID'] = data['api_id']
        telegram_listener.api_id = data['api_id']
    if 'api_hash' in data:
        os.environ['TELEGRAM_API_HASH'] = data['api_hash']
        telegram_listener.api_hash = data['api_hash']
    if 'target_channel' in data:
        os.environ['TELEGRAM_TARGET_CHANNEL'] = data['target_channel']
        telegram_listener.target_channel = data['target_channel']
        
    return jsonify({'status': 'success', 'message': 'Configuration updated (Session only)'})

@telegram_signal_bp.route('/login', methods=['POST'])
@check_session_validity
async def login_request():
    data = request.json
    phone = data.get('phone')
    
    if not phone:
        return jsonify({'status': 'error', 'message': 'Phone number required'}), 400
        
    try:
        phone_hash = await telegram_listener.send_code_request(phone)
        session['phone_hash'] = phone_hash.phone_code_hash
        session['login_phone'] = phone
        return jsonify({'status': 'success', 'message': 'OTP Sent'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@telegram_signal_bp.route('/verify-otp', methods=['POST'])
@check_session_validity
async def verify_otp():
    data = request.json
    otp = data.get('otp')
    phone = session.get('login_phone')
    
    if not otp or not phone:
        return jsonify({'status': 'error', 'message': 'OTP or Phone missing'}), 400
        
    try:
        await telegram_listener.sign_in(phone, otp)
        return jsonify({'status': 'success', 'message': 'Logged in successfully!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@telegram_signal_bp.route('/status')
@check_session_validity
def status():
    return jsonify({
        'is_running': telegram_listener.is_running,
        'target_channel': telegram_listener.target_channel
    })

@telegram_signal_bp.route('/history')
@check_session_validity
def history():
    return jsonify(telegram_listener.get_history())
