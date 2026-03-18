import re
from linebot.v3.messaging import FlexMessage, TextMessage


def _extract_youtube_video_id(url: str) -> str | None:
    """從 YouTube URL 或裸 video ID 提取 video_id"""
    if not url:
        return None
    # 完整 URL 格式
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    # 裸 video ID（11 字元）
    if re.fullmatch(r'[a-zA-Z0-9_-]{11}', url):
        return url
    return None


def _build_video_bubble_dict(title: str, url: str, thumbnail: str) -> dict:
    """建構單張影片 Bubble 的 dict"""
    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": thumbnail,
            "size": "full",
            "aspectRatio": "16:9",
            "aspectMode": "cover",
            "action": {"type": "uri", "uri": url},
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": title,
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                    "maxLines": 2,
                }
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "uri", "label": "觀看影片", "uri": url},
                    "style": "primary",
                    "color": "#FF0000",
                }
            ],
        },
    }


def build_line_messages(answer: str, ui_hints: list) -> list:
    """
    將 answer + ui_hints 轉換為 LINE Message 物件列表。

    ui_hints 格式範例:
    [{"ui_type": "VIDEO_CARD", "items": [{"source": "https://...", "title": "..."}]}]
    """
    # 收集所有 VIDEO_CARD items
    video_items = []
    for hint in ui_hints:
        if hint.get("ui_type") != "VIDEO_CARD":
            continue
        for item in hint.get("items", []):
            video_items.append(item)

    # 去重（依 video_id）
    seen_ids = set()
    unique_videos = []
    for item in video_items:
        # 優先取 url（完整 YouTube URL），fallback 到 source
        raw_url = item.get("url") or item.get("source", "")
        video_id = _extract_youtube_video_id(raw_url)
        if not video_id:
            # source 可能是裸 video ID
            video_id = _extract_youtube_video_id(item.get("source", ""))
        if not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        full_url = raw_url if raw_url.startswith("http") else f"https://www.youtube.com/watch?v={video_id}"
        unique_videos.append({
            "title": item.get("title", "教學影片"),
            "url": full_url,
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        })

    # 無有效影片 → 降級純文字
    if not unique_videos:
        print("  [UI Factory] 回覆類型: TEXT（純文字）")
        return [TextMessage(text=answer)]

    # 上限 10 張（LINE Carousel 限制）
    unique_videos = unique_videos[:10]

    # 建構 FlexMessage
    bubbles = [
        _build_video_bubble_dict(v["title"], v["url"], v["thumbnail"])
        for v in unique_videos
    ]

    if len(bubbles) == 1:
        contents_dict = bubbles[0]
        print(f"  [UI Factory] 回覆類型: VIDEO_CARD（單張影片卡片）— {unique_videos[0]['title']}")
    else:
        contents_dict = {"type": "carousel", "contents": bubbles}
        print(f"  [UI Factory] 回覆類型: VIDEO_CARD（輪播 {len(bubbles)} 張影片卡片）")

    flex_msg = FlexMessage.from_dict({
        "type": "flex",
        "altText": "教學影片推薦",
        "contents": contents_dict,
    })

    return [TextMessage(text=answer), flex_msg]
