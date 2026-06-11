# 🎬 YouTube Download Service

سيرفر تحميل خاص بيشتغل على VPS بـ IP نظيف.
بيحل مشكلة حظر YouTube على Railway.

## المميزات
- ✅ IP نظيف — YouTube مش بيحجبه
- ✅ رفع مباشر على Supabase — مفيش OOM
- ✅ Streaming — مبيحملش الملف كله في الرام
- ✅ FastAPI — سريع وآمن

## التثبيت على VPS

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install yt-dlp and ffmpeg
pip install -U yt-dlp
apt install ffmpeg

# 3. Set environment variables
cp .env.example .env
# Edit .env with your values

# 4. Run the service
python main.py

# Or with systemd (production)
sudo cp download-service.service /etc/systemd/system/
sudo systemctl enable download-service
sudo systemctl start download-service
```

## API Endpoints

### GET /download
Download a video and upload to Supabase.

**Parameters:**
- `url` (required): Video URL
- `quality` (optional): best, medium, low, audio (default: best)
- `platform` (optional): telegram, whatsapp (default: telegram)
- `lang` (optional): ar, en (default: ar)

**Response:**
```json
{
  "success": true,
  "url": "https://xxx.supabase.co/storage/v1/object/public/Downloads/telegram/...",
  "title": "Video Title",
  "duration": 300,
  "height": 720,
  "size_mb": 45.2,
  "quality": "720p"
}
```

### GET /health
Health check endpoint.
