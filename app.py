from flask import Flask, render_template, request, Response, jsonify, session
import google.generativeai as genai
import json
import os
from datetime import datetime
import threading
import atexit

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-this'  # Thay đổi key này

# Cấu hình Gemini API
API_KEY = ""
genai.configure(api_key=API_KEY)

# Khởi tạo model
model = genai.GenerativeModel("gemini-2.5-flash")

# Biến global
chat_session = None
current_topic = None

# Cấu hình chủ đề
TOPICS = {
    'que_huong': {
        'name': '🏠 Quê hương và hoài niệm',
        'description': 'Ký ức về quê nhà, món ăn truyền thống, ca dao tục ngữ, âm nhạc quê hương',
        'folder': 'que_huong'
    },
    'gia_dinh': {
        'name': '👨‍👩‍👧‍👦 Gia đình',
        'description': 'Liên lạc với người thân, truyền dạy văn hóa cho con cháu, kể chuyện gia đình',
        'folder': 'gia_dinh'
    },
    'suc_khoe': {
        'name': '💊 Sức khỏe',
        'description': 'Thuốc nam, chế độ ăn uống, tập thể dục cho người cao tuổi',
        'folder': 'suc_khoe'
    },
    'lich_su': {
        'name': '📚 Lịch sử',
        'description': 'Các triều đại, kháng chiến, nhân vật lịch sử, sự kiện đã trải qua',
        'folder': 'lich_su'
    },
    'tam_linh': {
        'name': '🙏 Tâm linh',
        'description': 'Phật giáo, thờ cúng tổ tiên, lễ hội truyền thống, phong thủy',
        'folder': 'tam_linh'
    }
}

# Cấu hình
CONTEXT_LIMIT = 20
SUMMARY_THRESHOLD = 50
SUMMARY_BATCH_SIZE = 30
USER_INFO_FILE = 'user_info.json'
TOPICS_DIR = 'topics'

file_lock = threading.Lock()

def ensure_topic_folders():
    """Tạo các thư mục chủ đề nếu chưa có"""
    if not os.path.exists(TOPICS_DIR):
        os.makedirs(TOPICS_DIR)
        print(f"Đã tạo thư mục chính: {TOPICS_DIR}")
    
    for topic_key, topic_info in TOPICS.items():
        topic_path = os.path.join(TOPICS_DIR, topic_info['folder'])
        if not os.path.exists(topic_path):
            os.makedirs(topic_path)
            print(f"Đã tạo thư mục: {topic_path}")

def get_topic_file_path(topic_key, file_type):
    """Lấy đường dẫn file theo chủ đề"""
    if topic_key not in TOPICS:
        raise ValueError(f"Chủ đề không hợp lệ: {topic_key}")
    
    topic_folder = TOPICS[topic_key]['folder']
    file_names = {
        'history': 'chat_history.json',
        'context': 'chat_context.json',
        'summary': 'chat_summary.json',
        'backup': 'full_conversation_backup.json'
    }
    
    if file_type not in file_names:
        raise ValueError(f"Loại file không hợp lệ: {file_type}")
    
    return os.path.join(TOPICS_DIR, topic_folder, file_names[file_type])

def clear_topic_files(topic_key):
    """Xóa tất cả file của một chủ đề"""
    try:
        for file_type in ['history', 'context', 'summary', 'backup']:
            file_path = get_topic_file_path(topic_key, file_type)
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Đã xóa file {file_path}")
    except Exception as e:
        print(f"Lỗi khi xóa file chủ đề {topic_key}: {e}")

def clear_all_topic_files():
    """Xóa tất cả file của tất cả chủ đề"""
    try:
        for topic_key in TOPICS.keys():
            clear_topic_files(topic_key)
    except Exception as e:
        print(f"Lỗi khi xóa tất cả file: {e}")

def load_user_info():
    """Đọc thông tin người dùng từ file JSON"""
    try:
        if os.path.exists(USER_INFO_FILE):
            with open(USER_INFO_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            print(f"Không tìm thấy file {USER_INFO_FILE}")
            return {}
    except Exception as e:
        print(f"Lỗi đọc file thông tin người dùng: {e}")
        return {}

def get_dialect_style(hometown):
    """Lấy đặc điểm giọng nói theo quê quán"""
    dialect_map = {
        # Miền Bắc
        "Hà Nội": "giọng Hà Nội, dùng 'ạ', 'ưa', 'thưa', lịch sự trang trọng",
        "Hải Phòng": "giọng Hải Phòng, thân thiện, dùng 'nhé', 'đấy', 'này'",
        "Hải Dương": "giọng Hải Dương, dùng 'nhỉ', 'đấy nhé', thân mật",
        "Nam Định": "giọng Nam Định, dùng 'nhỉ', 'đó', 'này', giọng đặc trưng",
        "Thái Bình": "giọng Thái Bình, dùng 'nhỉ', 'đấy', 'này'",
        "Nghệ An": "giọng Nghệ An, dùng 'nhỉ', 'đó', 'này', có thể nói 'gi' thành 'di'",
        "Hà Tĩnh": "giọng Hà Tĩnh, dùng 'nhỉ', 'đó', 'này'",
        "Quảng Bình": "giọng Quảng Bình, dùng 'nhỉ', 'đó', có đặc trưng riêng",
        "Quảng Trị": "giọng Quảng Trị, dùng 'nhỉ', 'đó'",
        "Thừa Thiên Huế": "giọng Huế, dùng 'nhỉ', 'đó', 'mình', nhẹ nhàng, dịu dàng",
        
        # Miền Trung
        "Đà Nẵng": "giọng Đà Nẵng, dùng 'nhỉ', 'đó', 'mình', thân thiện",
        "Quảng Nam": "giọng Quảng Nam, dùng 'nhỉ', 'đó', 'mình'",
        "Quảng Ngãi": "giọng Quảng Ngãi, dùng 'nhỉ', 'đó'",
        "Bình Định": "giọng Bình Định, dùng 'nhỉ', 'đó', 'mình'",
        "Phú Yên": "giọng Phú Yên, dùng 'nhỉ', 'đó'",
        "Khánh Hòa": "giọng Khánh Hòa, dùng 'nhỉ', 'đó', 'mình'",
        "Ninh Thuận": "giọng Ninh Thuận, dùng 'nhỉ', 'đó'",
        "Bình Thuận": "giọng Bình Thuận, dùng 'nhỉ', 'đó'",
        "Kon Tum": "giọng Kon Tum, dùng 'nhỉ', 'đó'",
        "Gia Lai": "giọng Gia Lai, dùng 'nhỉ', 'đó'",
        "Đắk Lắk": "giọng Đắk Lắk, dùng 'nhỉ', 'đó'",
        "Đắk Nông": "giọng Đắk Nông, dùng 'nhỉ', 'đó'",
        "Lâm Đồng": "giọng Lâm Đồng, dùng 'nhỉ', 'đó', 'mình'",
        
        # Miền Nam
        "TP.HCM": "giọng Sài Gòn, dùng 'nhé', 'đó', 'mình', 'nha', thân thiện thoải mái",
        "Hồ Chí Minh": "giọng Sài Gòn, dùng 'nhé', 'đó', 'mình', 'nha', thân thiện thoải mái",
        "Bình Dương": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Đồng Nai": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Bà Rịa - Vũng Tàu": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Tây Ninh": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Bình Phước": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Long An": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Tiền Giang": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Bến Tre": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Trà Vinh": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Vĩnh Long": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Đồng Tháp": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "An Giang": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Kiên Giang": "giọng Nam Bộ, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Cần Thơ": "giọng Cần Thơ, dùng 'nhé', 'đó', 'mình', 'nha', giọng miền Tây",
        "Hậu Giang": "giọng miền Tây, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Sóc Trăng": "giọng miền Tây, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Bạc Liêu": "giọng miền Tây, dùng 'nhé', 'đó', 'mình', 'nha'",
        "Cà Mau": "giọng miền Tây, dùng 'nhé', 'đó', 'mình', 'nha'"
    }
    
    return dialect_map.get(hometown, "giọng miền, dùng từ ngữ thân thiện")

def get_topic_specific_prompt(topic_key):
    """Tạo prompt đặc biệt cho từng chủ đề"""
    topic_prompts = {
        'que_huong': """
        BẠN LÀ CHUYÊN GIA VỀ QUÊ HƯƠNG VÀ HOÀI NIỆM:
        - Chia sẻ về món ăn quê hương, cách nấu truyền thống, nguyên liệu đặc biệt
        - Kể về phong cảnh, con người, làng xóm quê nhà
        - Nhớ về ca dao, tục ngữ, truyện cổ tích, câu chuyện dân gian
        - Âm nhạc quê hương (dân ca, quan họ, hát chèo, nhạc Trịnh Công Sơn, Phạm Duy...)
        - Lễ hội, tết cổ truyền, phong tục tập quán
        - Giúp người xa quê giữ gìn nét văn hóa, tìm lại cảm giác quê nhà
        - Chia sẻ cách nấu các món ăn quê với nguyên liệu có sẵn ở nước ngoài
        """,
        
        'gia_dinh': """
        BẠN LÀ CHUYÊN GIA VỀ GIA ĐÌNH:
        - Cách giữ liên lạc với người thân ở Việt Nam (điện thoại, video call, gửi tiền)
        - Truyền dạy tiếng Việt, văn hóa, lịch sử cho con cháu
        - Kể chuyện về gia đình, tổ tiên, dòng họ
        - Quan hệ với cộng đồng người Việt ở nước ngoài
        - Cách tổ chức lễ gia đình theo truyền thống (cưới hỏi, thôi nôi, sinh nhật tuổi...)
        - Giáo dục con cháu về văn hóa Việt, dạy con hiếu thảo
        - Xử lý xung đột thế hệ, cách cân bằng văn hóa Việt và nước ngoài
        - Cách duy trì tình cảm gia đình khi xa cách
        """,
        
        'suc_khoe': """
        BẠN LÀ CHUYÊN GIA VỀ SỨC KHỎE:
        - Thuốc nam, bài thuốc dân gian, cách pha chế từ thảo dược
        - Chế độ ăn uống cho người cao tuổi, món ăn bổ dưỡng
        - Tập thể dục phù hợp (thái cực quyền, đi bộ, yoga, khí công...)
        - Chăm sóc sức khỏe ở nước ngoài, tìm bác sĩ, dịch vụ y tế
        - Phòng ngừa bệnh tật (tiểu đường, huyết áp, tim mạch...)
        - Sống khỏe mạnh tuổi cao, giữ gìn sức khỏe tinh thần
        - Cách chăm sóc khi ốm đau, điều dưỡng tại nhà
        - Dinh dưỡng hợp lý, thực phẩm tốt cho sức khỏe
        """,
        
        'lich_su': """
        BẠN LÀ CHUYÊN GIA VỀ LỊCH SỬ VIỆT NAM:
        - Các triều đại (Lý, Trần, Lê, Nguyễn...), vua chúa nổi tiếng
        - Cuộc kháng chiến chống Pháp, chống Mỹ, các cuộc chiến tranh
        - Nhân vật lịch sử (Trần Hưng Đạo, Nguyễn Trãi, Hồ Chí Minh, Võ Nguyên Giáp...)
        - Lịch sử địa phương, quê hương, các vùng miền
        - Những sự kiện lịch sử quan trọng (Bạch Đằng, Điện Biên Phủ, 30/4/1975...)
        - Chia sẻ kinh nghiệm sống qua các thời kỳ lịch sử
        - Văn hóa, xã hội qua các giai đoạn lịch sử
        - Bài học từ lịch sử, truyền đạt cho thế hệ trẻ
        """,
        
        'tam_linh': """
        BẠN LÀ CHUYÊN GIA VỀ VĂN HÓA TÂM LINH:
        - Phật giáo, tín ngưỡng Việt Nam, đạo Cao Đài, Hòa Hảo
        - Cách thờ cúng tổ tiên ở nước ngoài, bài trí bàn thờ
        - Lễ hội, tết cổ truyền (Tết Nguyên Đán, Tết Trung Thu, Giỗ Tổ Hùng Vương...)
        - Phong thủy, xem ngày tốt, chọn hướng nhà
        - Đạo đức, triết lý sống, tu dưỡng đạo đức
        - Tâm linh trong cuộc sống hàng ngày, cách sống có ý nghĩa
        - Cầu nguyện, tụng kinh, thiền định
        - Giải thích các tục lệ, nghi lễ truyền thống
        """
    }
    
    return topic_prompts.get(topic_key, "")

def get_system_prompt(topic_key):
    """Tạo system prompt với thông tin cá nhân và chủ đề"""
    try:
        user_info = load_user_info()
        
        # Prompt cơ bản
        prompt = "Bạn là trợ lý AI thân thiện và hữu ích. "
        
        # Cách gọi
        call_style = user_info.get('call_style', 'bác')
        prompt += f"QUAN TRỌNG: Luôn luôn gọi người dùng là '{call_style}' trong mọi câu trả lời. "
        
        # Thông tin cá nhân cơ bản
        if user_info.get('name'):
            prompt += f"Tên người dùng: {user_info['name']}. "
        
        if user_info.get('age'):
            prompt += f"Tuổi: {user_info['age']}. "
        
        if user_info.get('gender'):
            prompt += f"Giới tính: {user_info['gender']}. "
        
        if user_info.get('location'):
            prompt += f"Nơi ở hiện tại: {user_info['location']}. "
        
        if user_info.get('hometown'):
            prompt += f"Quê quán: {user_info['hometown']}. "
        
        if user_info.get('occupation'):
            prompt += f"Nghề nghiệp: {user_info['occupation']}. "
        
        if user_info.get('family'):
            prompt += f"Gia đình: {user_info['family']}. "
        
        if user_info.get('health'):
            prompt += f"Tình trạng sức khỏe: {user_info['health']}. "
        
        # Đặc điểm giọng nói theo quê quán
        if user_info.get('hometown'):
            dialect_style = get_dialect_style(user_info['hometown'])
            prompt += f"QUAN TRỌNG VỀ GIỌNG NÓI: Trả lời theo {dialect_style}. "
            prompt += "Sử dụng từ ngữ và cách nói đặc trưng của vùng miền này một cách tự nhiên. "
        
        # Thêm prompt đặc biệt cho chủ đề
        prompt += get_topic_specific_prompt(topic_key)
        
        # Đặc biệt cho người xa quê
        if user_info.get('location') and user_info.get('hometown'):
            if user_info['location'] != user_info['hometown']:
                prompt += f"""
                
                ĐẶCBIỆT: Người dùng hiện đang sống xa quê ({user_info['location']} - xa {user_info['hometown']}):
                - Thể hiện sự thấu hiểu nỗi nhớ quê hương
                - Chia sẻ cách duy trì văn hóa Việt ở nước ngoài
                - Gợi ý cách liên lạc với người thân
                - Động viên khi họ buồn nhớ nhà
                - Kể chuyện về cộng đồng người Việt ở nước ngoài
                """
        
        # Hướng dẫn chung
        prompt += """
        
        HƯỚNG DẪN CHUNG:
        - Trả lời thân thiện, ngắn gọn, dễ hiểu, phù hợp với người cao tuổi
        - Tránh dùng từ chuyên môn phức tạp, viết tắt
        - Luôn lịch sự và kiên nhẫn
        - KHÔNG sử dụng markdown formatting như **text**, *text*, hoặc bất kỳ ký tự đặc biệt nào
        - Chỉ trả lời bằng văn bản thuần túy, không có ký tự đặc biệt, không in đậm
        - Trả lời chi tiết, có cảm xúc và gợi nhớ về quê hương
        - Khuyến khích chia sẻ và kể chuyện
        """
        
        return prompt
        
    except Exception as e:
        print(f"Lỗi tạo system prompt: {e}")
        return (
            "Bạn là trợ lý AI thân thiện. "
            "QUAN TRỌNG: Luôn luôn gọi người dùng là 'bác' trong mọi câu trả lời. "
            "Trả lời ngắn gọn, dễ hiểu, dùng từ ngữ đơn giản, phù hợp với người cao tuổi Việt Nam. "
            "Tránh dùng từ chuyên môn, viết tắt. Luôn lịch sự và kiên nhẫn. "
            "KHÔNG sử dụng markdown formatting. Chỉ trả lời bằng văn bản thuần túy."
        )

def load_chat_history(topic_key):
    """Đọc lịch sử hội thoại theo chủ đề"""
    try:
        file_path = get_topic_file_path(topic_key, 'history')
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('messages', [])
        return []
    except Exception as e:
        print(f"Lỗi đọc file lịch sử {topic_key}: {e}")
        return []

def save_chat_history(topic_key, messages):
    """Lưu lịch sử hội thoại theo chủ đề"""
    try:
        with file_lock:
            file_path = get_topic_file_path(topic_key, 'history')
            chat_data = {
                'topic': topic_key,
                'topic_name': TOPICS[topic_key]['name'],
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'total_messages': len(messages),
                'messages': messages
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(chat_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi ghi file lịch sử {topic_key}: {e}")

def load_full_backup(topic_key):
    """Đọc backup theo chủ đề"""
    try:
        file_path = get_topic_file_path(topic_key, 'backup')
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('messages', [])
        return []
    except Exception as e:
        print(f"Lỗi đọc file backup {topic_key}: {e}")
        return []

def save_full_backup(topic_key, messages):
    """Lưu backup theo chủ đề"""
    try:
        with file_lock:
            file_path = get_topic_file_path(topic_key, 'backup')
            backup_data = {
                'topic': topic_key,
                'topic_name': TOPICS[topic_key]['name'],
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'total_messages': len(messages),
                'description': f'Backup toàn bộ hội thoại chủ đề {TOPICS[topic_key]["name"]}',
                'messages': messages
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi ghi file backup {topic_key}: {e}")

def load_summary_data(topic_key):
    """Đọc dữ liệu tóm tắt theo chủ đề"""
    try:
        file_path = get_topic_file_path(topic_key, 'summary')
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'topic': topic_key,
            'topic_name': TOPICS[topic_key]['name'],
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'summary_version': 1,
            'total_conversations_summarized': 0,
            'summary_layers': []
        }
    except Exception as e:
        print(f"Lỗi đọc file tóm tắt {topic_key}: {e}")
        return {
            'topic': topic_key,
            'topic_name': TOPICS[topic_key]['name'],
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'summary_version': 1,
            'total_conversations_summarized': 0,
            'summary_layers': []
        }

def save_summary_data(topic_key, summary_data):
    """Lưu dữ liệu tóm tắt theo chủ đề"""
    try:
        with file_lock:
            file_path = get_topic_file_path(topic_key, 'summary')
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(summary_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi ghi file tóm tắt {topic_key}: {e}")

def save_chat_context(topic_key, messages):
    """Lưu context gần nhất theo chủ đề"""
    try:
        with file_lock:
            file_path = get_topic_file_path(topic_key, 'context')
            recent_messages = messages[-CONTEXT_LIMIT:] if len(messages) > CONTEXT_LIMIT else messages
            
            context_data = {
                'topic': topic_key,
                'topic_name': TOPICS[topic_key]['name'],
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'context_limit': CONTEXT_LIMIT,
                'recent_messages': recent_messages,
                'total_messages_count': len(messages)
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(context_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi ghi file context {topic_key}: {e}")

def should_create_summary(messages):
    """Kiểm tra có cần tạo tóm tắt không"""
    return len(messages) > SUMMARY_THRESHOLD

def create_conversation_summary(topic_key, conversations):
    """Tạo tóm tắt từ một batch conversations"""
    try:
        topic_name = TOPICS[topic_key]['name']
        
        # Tạo prompt để tóm tắt
        summary_prompt = f"""
Hãy tóm tắt {len(conversations)} đoạn hội thoại về chủ đề {topic_name} một cách ngắn gọn và súc tích:

QUAN TRỌNG:
1. Trích xuất thông tin cá nhân quan trọng (tên, tuổi, địa chỉ, sở thích)
2. Ghi nhận các chủ đề con được thảo luận trong {topic_name}
3. Lưu lại các quyết định hoặc kết luận quan trọng
4. Tóm tắt ngắn gọn, không quá 200 từ

Các đoạn hội thoại:
"""
        
        for i, conv in enumerate(conversations):
            summary_prompt += f"\nĐoạn {i+1}:\n"
            summary_prompt += f"User: {conv['user']}\n"
            summary_prompt += f"Bot: {conv['bot']}\n"
        
        summary_prompt += """

Hãy trả lời theo format JSON:
{
    "summary": "Tóm tắt chung ngắn gọn...",
    "personal_info": ["thông tin cá nhân quan trọng"],
    "key_topics": ["chủ đề con được thảo luận"],
    "important_facts": ["sự kiện quan trọng"]
}
"""
        
        # Tạo session riêng để tóm tắt
        summary_session = model.start_chat()
        response = summary_session.send_message(summary_prompt)
        
        # Parse JSON response
        try:
            summary_data = json.loads(response.text)
            return summary_data
        except json.JSONDecodeError:
            # Fallback nếu không parse được JSON
            return {
                "summary": f"Tóm tắt {len(conversations)} đoạn hội thoại về {topic_name}",
                "personal_info": [],
                "key_topics": [topic_name],
                "important_facts": []
            }
        
    except Exception as e:
        print(f"Lỗi tạo tóm tắt {topic_key}: {e}")
        return {
            "summary": f"Tóm tắt {len(conversations)} đoạn hội thoại",
            "personal_info": [],
            "key_topics": [],
            "important_facts": []
        }

def update_summary_file(topic_key, conversations_to_summarize):
    """Cập nhật file tóm tắt theo chủ đề"""
    try:
        # Load existing summary
        summary_data = load_summary_data(topic_key)
        
        # Tạo tóm tắt cho batch mới
        new_summary = create_conversation_summary(topic_key, conversations_to_summarize)
        
        # Thêm layer mới
        start_range = summary_data['total_conversations_summarized'] + 1
        end_range = summary_data['total_conversations_summarized'] + len(conversations_to_summarize)
        
        new_layer = {
            'layer': len(summary_data['summary_layers']) + 1,
            'conversations_range': f"{start_range}-{end_range}",
            'summary': new_summary['summary'],
            'key_topics': new_summary['key_topics'],
            'important_facts': new_summary['personal_info'] + new_summary['important_facts']
        }
        
        summary_data['summary_layers'].append(new_layer)
        summary_data['total_conversations_summarized'] += len(conversations_to_summarize)
        summary_data['last_updated'] = datetime.now().isoformat()
        
        # Save updated summary
        save_summary_data(topic_key, summary_data)
        print(f"Đã tạo tóm tắt cho {len(conversations_to_summarize)} đoạn hội thoại chủ đề {topic_key}")
        
    except Exception as e:
        print(f"Lỗi cập nhật tóm tắt {topic_key}: {e}")

def manage_context_and_summary(topic_key, messages):
    """Quản lý context và tóm tắt theo chủ đề"""
    if should_create_summary(messages):
        # Tính toán cần tóm tắt bao nhiêu đoạn
        conversations_to_summarize = len(messages) - CONTEXT_LIMIT
        
        if conversations_to_summarize >= SUMMARY_BATCH_SIZE:
            # Lấy các đoạn cần tóm tắt (cũ nhất)
            old_conversations = messages[:SUMMARY_BATCH_SIZE]
            
            # Tạo tóm tắt
            update_summary_file(topic_key, old_conversations)
            
            # Giữ lại phần còn lại (XÓA các đoạn cũ khỏi working file)
            remaining_messages = messages[SUMMARY_BATCH_SIZE:]
            
            print(f"Đã tóm tắt {SUMMARY_BATCH_SIZE} đoạn cũ chủ đề {topic_key}, còn lại {len(remaining_messages)} đoạn")
            return remaining_messages
    
    return messages

def init_chat_session(topic_key):
    """Khởi tạo chat session theo chủ đề"""
    global chat_session, current_topic
    try:
        current_topic = topic_key
        system_prompt = get_system_prompt(topic_key)
        
        chat_session = model.start_chat(
            history=[
                {
                    "role": "user",
                    "parts": [system_prompt]
                },
                {
                    "role": "model", 
                    "parts": [f"Tôi hiểu rồi. Tôi sẽ trò chuyện với bác về chủ đề {TOPICS[topic_key]['name']} theo thông tin đã cung cấp."]
                }
            ]
        )
        print(f"Chat session đã được khởi tạo cho chủ đề: {topic_key}")
    except Exception as e:
        print(f"Lỗi khởi tạo chat session: {e}")
        chat_session = None

def restore_chat_session_with_summary(topic_key):
    """Khôi phục session với tóm tắt + context gần nhất theo chủ đề"""
    global chat_session, current_topic
    
    try:
        current_topic = topic_key
        
        # Load summary và context
        summary_data = load_summary_data(topic_key)
        recent_messages = load_chat_history(topic_key)
        
        # Tạo context prompt với tóm tắt
        context_prompt = get_system_prompt(topic_key)
        
        if summary_data and summary_data['summary_layers']:
            context_prompt += f"\n\nTHÔNG TIN TỪ CÁC CUỘC HỘI THOẠI TRƯỚC VỀ {TOPICS[topic_key]['name'].upper()}:\n"
            
            for layer in summary_data['summary_layers']:
                context_prompt += f"\nGiai đoạn {layer['conversations_range']}:\n"
                context_prompt += f"- Tóm tắt: {layer['summary']}\n"
                if layer['key_topics']:
                    context_prompt += f"- Chủ đề chính: {', '.join(layer['key_topics'])}\n"
                if layer['important_facts']:
                    context_prompt += f"- Thông tin quan trọng: {', '.join(layer['important_facts'])}\n"
        
        # Tạo history cho Gemini
        gemini_history = [
            {
                "role": "user",
                "parts": [context_prompt]
            },
            {
                "role": "model",
                "parts": [f"Tôi đã hiểu thông tin từ các cuộc hội thoại trước về {TOPICS[topic_key]['name']} và sẽ tham khảo khi trả lời bác."]
            }
        ]
        
        # Thêm context gần nhất
        context_limit = min(CONTEXT_LIMIT, len(recent_messages))
        for chat in recent_messages[-context_limit:]:
            gemini_history.append({
                "role": "user",
                "parts": [chat['user']]
            })
            gemini_history.append({
                "role": "model",
                "parts": [chat['bot']]
            })
        
        chat_session = model.start_chat(history=gemini_history)
        
        summary_count = len(summary_data['summary_layers']) if summary_data['summary_layers'] else 0
        print(f"Khôi phục session chủ đề {topic_key} với {summary_count} tóm tắt + {context_limit} tin nhắn gần nhất")
        
    except Exception as e:
        print(f"Lỗi khôi phục session {topic_key}: {e}")
        init_chat_session(topic_key)

def add_message_to_history(topic_key, user_message, bot_response):
    """Thêm tin nhắn vào lịch sử theo chủ đề"""
    new_message = {
        'timestamp': datetime.now().isoformat(),
        'user': user_message,
        'bot': bot_response
    }
    
    # 1. Cập nhật FULL BACKUP trước (không bao giờ bị xóa)
    full_backup = load_full_backup(topic_key)
    full_backup.append(new_message)
    save_full_backup(topic_key, full_backup)
    
    # 2. Cập nhật working history
    messages = load_chat_history(topic_key)
    messages.append(new_message)
    
    # 3. Quản lý context và tóm tắt (có thể cắt bớt messages)
    messages = manage_context_and_summary(topic_key, messages)
    
    # 4. Lưu lại working files
    save_chat_history(topic_key, messages)
    save_chat_context(topic_key, messages)

def get_topic_statistics(topic_key):
    """Lấy thống kê chat theo chủ đề"""
    try:
        current_messages = load_chat_history(topic_key)
        full_backup = load_full_backup(topic_key)
        summary_data = load_summary_data(topic_key)
        
        return {
            'topic': topic_key,
            'topic_name': TOPICS[topic_key]['name'],
            'current_messages': len(current_messages),
            'full_backup_messages': len(full_backup),
            'summarized_conversations': summary_data.get('total_conversations_summarized', 0),
            'total_conversations': len(full_backup),
            'summary_layers': len(summary_data.get('summary_layers', [])),
            'session_active': chat_session is not None and current_topic == topic_key
        }
    except Exception as e:
        print(f"Lỗi lấy thống kê {topic_key}: {e}")
        return {
            'topic': topic_key,
            'topic_name': TOPICS[topic_key]['name'],
            'current_messages': 0,
            'full_backup_messages': 0,
            'summarized_conversations': 0,
            'total_conversations': 0,
            'summary_layers': 0,
            'session_active': False
        }

def get_all_topics_statistics():
    """Lấy thống kê tất cả chủ đề"""
    all_stats = {}
    for topic_key in TOPICS.keys():
        all_stats[topic_key] = get_topic_statistics(topic_key)
    return all_stats

# === ROUTES ===

@app.route('/')
def index():
    """Trang chọn chủ đề"""
    return render_template('index.html', topics=TOPICS)

@app.route('/chat/<topic_key>')
def chat_page(topic_key):
    """Trang chat theo chủ đề"""
    if topic_key not in TOPICS:
        return "Chủ đề không hợp lệ", 404
    
    session['current_topic'] = topic_key
    topic_info = TOPICS[topic_key]
    
    # Load lịch sử chat
    messages = load_chat_history(topic_key)
    
    return render_template('chat.html', 
                         topic_key=topic_key,
                         topic_info=topic_info,
                         messages=messages)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    """API chat"""
    global chat_session
    
    try:
        data = request.json
        user_message = data.get('message', '')
        topic_key = data.get('topic_key', '')
        
        if not user_message or not topic_key:
            return jsonify({'error': 'Thiếu thông tin'}), 400
        
        if topic_key not in TOPICS:
            return jsonify({'error': 'Chủ đề không hợp lệ'}), 400
        
        # Khởi tạo chat session nếu chưa có hoặc đổi chủ đề
        if chat_session is None or current_topic != topic_key:
            restore_chat_session_with_summary(topic_key)
        
        def generate():
            try:
                stream = chat_session.send_message(user_message, stream=True)
                
                bot_response = ""
                for chunk in stream:
                    if chunk.text:
                        bot_response += chunk.text
                        yield f"data: {json.dumps({'text': chunk.text})}\n\n"
                
                # Lưu vào lịch sử
                add_message_to_history(topic_key, user_message, bot_response)
                
                yield f"data: {json.dumps({'done': True})}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return Response(generate(), mimetype='text/plain')
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset_session', methods=['POST'])
def reset_session():
    """Reset chat session"""
    global chat_session, current_topic
    try:
        chat_session = None
        current_topic = None
        return jsonify({'success': True, 'message': 'Chat session đã được reset'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear_topic/<topic_key>', methods=['POST'])
def clear_topic(topic_key):
    """Xóa lịch sử một chủ đề"""
    if topic_key not in TOPICS:
        return jsonify({'error': 'Chủ đề không hợp lệ'}), 400
    
    try:
        clear_topic_files(topic_key)
        
        # Reset session nếu đang chat chủ đề này
        global chat_session, current_topic
        if current_topic == topic_key:
            chat_session = None
            current_topic = None
        
        return jsonify({'success': True, 'message': f'Đã xóa lịch sử chủ đề {TOPICS[topic_key]["name"]}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear_all_topics', methods=['POST'])
def clear_all_topics():
    """Xóa lịch sử tất cả chủ đề"""
    try:
        clear_all_topic_files()
        
        # Reset session
        global chat_session, current_topic
        chat_session = None
        current_topic = None
        
        return jsonify({'success': True, 'message': 'Đã xóa lịch sử tất cả chủ đề'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/topic_stats/<topic_key>', methods=['GET'])
def topic_stats(topic_key):
    """Lấy thống kê một chủ đề"""
    if topic_key not in TOPICS:
        return jsonify({'error': 'Chủ đề không hợp lệ'}), 400
    
    stats = get_topic_statistics(topic_key)
    return jsonify(stats)

@app.route('/api/all_stats', methods=['GET'])
def all_stats():
    """Lấy thống kê tất cả chủ đề"""
    stats = get_all_topics_statistics()
    return jsonify(stats)

@app.route('/api/export_topic/<topic_key>', methods=['GET'])
def export_topic(topic_key):
    """Export lịch sử một chủ đề"""
    if topic_key not in TOPICS:
        return jsonify({'error': 'Chủ đề không hợp lệ'}), 400
    
    try:
        current_messages = load_chat_history(topic_key)
        full_backup = load_full_backup(topic_key)
        summary_data = load_summary_data(topic_key)
        
        return jsonify({
            'success': True,
            'topic': topic_key,
            'topic_name': TOPICS[topic_key]['name'],
            'current_messages': current_messages,
            'full_backup_messages': full_backup,
            'summary_data': summary_data,
            'statistics': get_topic_statistics(topic_key)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_topic_backup/<topic_key>', methods=['GET'])
def export_topic_backup(topic_key):
    """Export backup một chủ đề"""
    if topic_key not in TOPICS:
        return jsonify({'error': 'Chủ đề không hợp lệ'}), 400
    
    try:
        full_backup = load_full_backup(topic_key)
        return jsonify({
            'success': True,
            'topic': topic_key,
            'topic_name': TOPICS[topic_key]['name'],
            'total_messages': len(full_backup),
            'messages': full_backup
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/user_info', methods=['GET'])
def get_user_info():
    """Xem thông tin người dùng hiện tại"""
    try:
        user_info = load_user_info()
        return jsonify({'success': True, 'user_info': user_info})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Tự động xóa file khi tắt server
# atexit.register(clear_all_topic_files)

if __name__ == '__main__':
    # Tạo các thư mục cần thiết
    ensure_topic_folders()
    
    print("=== KHỞI ĐỘNG TRỢ LÝ AI CHO NGƯỜI CAO TUỔI ===")
    print("Các chủ đề có sẵn:")
    for key, info in TOPICS.items():
        print(f"- {info['name']}: {info['description']}")
    print("=" * 50)
    
    try:
        app.run(debug=True, port=5000)
    except KeyboardInterrupt:
        print("\nĐang tắt server...")
        clear_all_topic_files()
