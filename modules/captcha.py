"""淘宝滑块验证识别与自动通过。

淘宝会随机在跳转后的页面弹「亲，请拖动下方滑块完成验证」，
挡住整页导致后续点击全部落空。这里做两件事：
1. 检测：无障碍树或 OCR 里出现滑块文案；
2. 通过：找到橙色手柄，用较慢的拟人轨迹向右拖到终点。
"""
import logging
import random
import time

from modules import ocr, ui

logger = logging.getLogger(__name__)

# 滑块页面的特征文案
HINTS = ('拖动下方滑块', '向右滑动验证', '按住滑块', '拖动滑块', '请完成验证', '通过验证')

# 兜底比例（找不到手柄时用）：手柄中心、拖动终点
HANDLE_RATIO = (0.18, 0.573)
END_RATIO = 0.92


def detected_in(nodes):
    """只看无障碍树（便宜），用于已有 dump 的场合。"""
    blob = ' '.join((n['text'] + ' ' + n['desc']) for n in nodes)
    return any(h in blob for h in HINTS)


def detect(d, nodes=None, use_ocr=True):
    """检测当前是否被滑块验证拦截。

    先看无障碍树；树里没有文案时再用 OCR（多花一次截图+识别）。
    """
    nodes = nodes if nodes is not None else ui.dump_nodes(d)
    if detected_in(nodes):
        return True
    if not use_ocr or not ocr.available():
        return False

    blob = ' '.join(t for t, _x, _y, _s in ocr.read_texts(d))
    return any(h in blob for h in HINTS)


def _is_orange(r, g, b):
    return r > 200 and 60 < g < 175 and b < 100


def _slider_from_image(path, screen_w, screen_h):
    """从截图里找滑块手柄和拖动终点，返回 (start_x, y, end_x)。

    手柄是橙色圆角方块，通常在「向右滑动验证」那一行的最左边。
    """
    from PIL import Image

    img = Image.open(path).convert('RGB')
    w, h = img.size
    px = img.load()

    # 1) 先用 OCR 找到「滑动验证」那一行的 y（同一张图只识别一次）
    band_y = None
    for text, _x, y, _s in ocr.read_image(path):
        if '滑动验证' in text or '拖动' in text:
            band_y = y
            break

    # 2) 在该行附近扫橙色手柄
    candidates = []
    if band_y is not None:
        y_from = max(0, band_y - int(h * 0.06))
        y_to = min(h, band_y + int(h * 0.06))
    else:
        y_from, y_to = int(h * 0.30), int(h * 0.85)

    max_run = max(3, int(w * 0.12 / 3))  # 手柄宽度不超过屏宽 12%
    for y in range(y_from, y_to, 3):
        run = 0
        start = 0
        for x in range(0, w, 3):
            r, g, b = px[x, y]
            if _is_orange(r, g, b):
                if run == 0:
                    start = x
                run += 1
            else:
                if 4 <= run <= max_run:
                    candidates.append((start + run * 3 // 2, y, run * 3))
                run = 0
        if 4 <= run <= max_run:
            candidates.append((start + run * 3 // 2, y, run * 3))

    if not candidates:
        logger.warning('未找到滑块手柄，按比例兜底')
        return (int(screen_w * HANDLE_RATIO[0]), int(screen_h * HANDLE_RATIO[1]),
                int(screen_w * END_RATIO))

    # 取最宽的那几行的**中间一行**：圆角会让首尾行变窄，但中间几行宽度相同，
    # 只取最宽的第一个会偏到上边缘
    widest = max(c[2] for c in candidates)
    same = sorted((c for c in candidates if c[2] >= widest * 0.9), key=lambda c: c[1])
    hx, hy, _w = same[len(same) // 2]
    scale_x = screen_w / float(w)
    scale_y = screen_h / float(h)
    return int(hx * scale_x), int(hy * scale_y), int(screen_w * END_RATIO)


def _drag(d, x1, y1, x2, y2):
    """慢速拖动：滑块会校验拖动时长和轨迹，不能用 0.3s 的直线 swipe。"""
    steps = 26
    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        x = x1 + (x2 - x1) * t
        y = y1 + random.uniform(-2, 2)
        points.append((int(x), int(y)))
    points += [(int(x2), int(y2))] * 4  # 到终点停一下再松手

    if d.device_type == 'hmdriver2':
        d.swipe(x1, y1, x2, y2, duration=1.2)
        return
    d.device.swipe_points(points, duration=1.2)


def solve(d, tries=3):
    """拖动滑块通过验证，返回是否成功。"""
    for i in range(tries):
        path = ocr.screenshot(d)
        w, h = d.display_size
        sx, sy, ex = _slider_from_image(path, w, h)
        logger.info('滑块验证：拖动 (%d,%d) -> (%d,%d)', sx, sy, ex, sy)
        try:
            _drag(d, sx, sy, ex, sy)
        except Exception as e:
            logger.warning('拖动滑块失败: %s', e)
            return False

        time.sleep(2.2)
        if not detect(d, use_ocr=True):
            logger.info('滑块验证已通过')
            return True
        logger.info('滑块验证未通过，重试（第%d次）', i + 1)
        time.sleep(1.2)

    logger.warning('滑块验证多次尝试仍未通过')
    return False


def handle(d, nodes=None):
    """检测并处理滑块验证；返回是否处理过（处理成功或本来就没有）。"""
    if not detect(d, nodes):
        return True

    logger.warning('检测到滑块验证，尝试自动通过')
    if solve(d):
        return True
    logger.warning('滑块验证未通过，本次任务可能失败')
    return False
