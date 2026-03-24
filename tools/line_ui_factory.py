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


def _build_download_bubble_dict(title: str, url: str, filename: str) -> dict:
    """建構單張下載按鈕 Bubble 的 dict"""
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "📄 官方說明書",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": title,
                    "weight": "bold",
                    "size": "xl",
                    "margin": "md",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": f"📎 {filename}",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "wrap": True,
                    "margin": "sm"
                },
                {
                    "type": "text",
                    "text": "點擊下方按鈕即可開啟或下載 PDF 檔案",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "wrap": True,
                    "margin": "sm"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "📥 立即下載",
                        "uri": url
                    }
                }
            ],
            "flex": 0
        }
    }


def build_line_messages(answer: str, ui_hints: list) -> list:
    """
    將 answer + ui_hints 轉換為 LINE Message 物件列表。

    ui_hints 格式範例:
    [{"ui_type": "VIDEO_CARD", "items": [{"source": "https://...", "title": "..."}]}]
    """
    # --- 處理 DOWNLOAD_CARD ---
    download_items = []
    for hint in ui_hints:
        if hint.get("ui_type") == "DOWNLOAD_CARD":
            for item in hint.get("items", []):
                if item.get("url") and item not in download_items:
                    download_items.append(item)

    if download_items:
        download_items = download_items[:10]
        bubbles = []
        for item in download_items:
            model = item.get("model", "")
            title = item.get("title") or (f"{model} 說明書" if model else "說明書檔案")
            filename = f"{model} 說明書.pdf" if model else "說明書.pdf"
            bubbles.append(_build_download_bubble_dict(title, item.get("url"), filename))

        contents_dict = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles}
        flex_msg = FlexMessage.from_dict({
            "type": "flex",
            "altText": "說明書下載連結",
            "contents": contents_dict,
        })
        print(f"  [UI Factory] 回覆類型: DOWNLOAD_CARD（{len(bubbles)} 張卡片）")
        return [TextMessage(text=answer), flex_msg]

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
        # 檢查是否包含特殊的分段標記
        if "\n===SPLIT_MSG===\n" in answer:
            parts = answer.split("\n===SPLIT_MSG===\n")
            print(f"  [UI Factory] 回覆類型: TEXT（分拆為 {len(parts)} 則純文字訊息）")
            return [TextMessage(text=part.strip()) for part in parts if part.strip()]
        else:
            print("  [UI Factory] 回覆類型: TEXT（單則純文字）")
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
