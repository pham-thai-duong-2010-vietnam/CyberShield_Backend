import json
import asyncio
import aiohttp
from flask import Flask, request, jsonify
from openai import AsyncOpenAI
import google.generativeai as genai

# Khởi tạo Flask app
app = Flask(__name__)

# Cấu hình API keys từ environment variables (sẽ được set trên Vercel)
GOOGLE_API_KEY = "AIzaSyBs5KjRQiDPsyqke-Ji_sKbIutuDwt6eWU"
OPENAI_API_KEY = "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"
OPENROUTER_API_KEY = "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"

# Cấu hình các API clients
genai.configure(api_key=GOOGLE_API_KEY)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Prompt chuẩn hóa cho tất cả các AI engines
UNIFIED_PROMPT = lambda text: f"""
Bạn là một hệ thống phân tích an toàn thông minh. Hãy phân tích đoạn tin nhắn sau và trả lời dưới dạng JSON với các key:

- "is_scam" (boolean): Đây có phải nội dung lừa đảo, độc hại, hoặc nguy hiểm không (vd:true, false)?
- "reason" (string): Giải thích ngắn gọn vì sao bị đánh giá như vậy.
- "types" (string): Các loại rủi ro tiềm ẩn (vd: "Lừa đảo", "bạo lực", v.v.).
- "score" (number 1-5): Mức độ nghiêm trọng (1 là nhẹ, 5 là cực kỳ nguy hiểm).
- "recommend" (string): Gợi ý hành động nên làm (vd: báo cáo, xoá, bỏ qua, cảnh giác, v.v.).

Đoạn tin nhắn: {text}
"""

async def analyze_with_gemini(text):
    """Phân tích văn bản bằng Google Gemini"""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = await model.generate_content_async(UNIFIED_PROMPT(text))
        # Loại bỏ các ký tự markdown nếu có
        json_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_text)
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        return None

async def analyze_with_openai(text):
    """Phân tích văn bản bằng OpenAI GPT"""
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": UNIFIED_PROMPT(text)}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"OpenAI API Error: {str(e)}")
        return None

async def synthesize_results_with_claude(analyses):
    """Tổng hợp kết quả từ các phân tích bằng OpenRouter/Claude"""
    try:
        prompt = f"""
Bạn là chuyên gia an ninh, hãy tổng hợp các phân tích sau thành một kết quả JSON cuối cùng và chính xác nhất với các key:
- "is_scam", "reason", "types", "score", "recommend".

--- CÁC PHÂN TÍCH ---
{json.dumps(analyses, ensure_ascii=False, indent=2)}
""".strip()
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}'},
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}
                }
            ) as response:
                data = await response.json()
                return json.loads(data['choices'][0]['message']['content'])
    except Exception as e:
        print(f"Claude Synthesizer Error: {str(e)}")
        return None

@app.route('/api/analyze', methods=['POST'])
def analyze_text():
    """Endpoint chính để phân tích văn bản"""
    try:
        # Lấy văn bản từ request
        data = request.get_json()
        text = data.get('text', '')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        # Thực hiện phân tích bất đồng bộ
        analyses = asyncio.run(analyze_multiple_engines(text))
        
        # Lọc các kết quả thành công
        successful_analyses = [a for a in analyses if a is not None]
        
        if not successful_analyses:
            return jsonify({'error': 'All primary analysis AIs failed'}), 500
        
        # Tổng hợp kết quả cuối cùng
        final_result = asyncio.run(synthesize_results_with_claude(successful_analyses))
        
        if not final_result:
            return jsonify({'error': 'Synthesis AI failed'}), 500
            
        return jsonify(final_result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

async def analyze_multiple_engines(text):
    """Phân tích văn bản bằng nhiều AI engines song song"""
    tasks = [
        analyze_with_gemini(text),
        analyze_with_openai(text)
    ]
    return await asyncio.gather(*tasks)

# Hàm chạy Flask app (chỉ dùng cho local testing)
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000)
