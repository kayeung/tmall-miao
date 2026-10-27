"""截图 OCR 定位工具。

芭芭农场这类 H5 是把内容画在 canvas 上的，无障碍树里没有按钮文案，
只能用截图 + OCR 找到「集肥料」「点击领取」这类按钮的屏幕坐标。
"""
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_engine = None
_available = None


def available():
    """当前环境是否装了 OCR（没装就退回坐标点击）。"""
    global _available
    if _available is None:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            _available = True
        except Exception as e:
            logger.warning('未安装 OCR 组件（%s），将退回坐标点击', e)
            _available = False
    return _available


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        logger.debug('初始化 OCR 引擎')
        _engine = RapidOCR()
    return _engine


def screenshot(d, path=None):
    """截图到本地文件，返回路径。"""
    path = path or os.path.join(tempfile.gettempdir(), 'tmall_ocr_shot.png')
    d.device.screenshot(path)
    return path


def read_image(path, max_side=2000):
    """对已有截图做 OCR，返回 [(文字, 中心x, 中心y, 置信度), ...]。

    坐标一律换算回**原图**像素，所以不同分辨率的手机拿到的都是可直接点击的坐标。
    图片长边超过 max_side 时先等比缩小再识别（提速），结果坐标再乘回去。
    """
    if not available():
        return []

    from PIL import Image

    img = Image.open(path).convert('RGB')
    w0, h0 = img.size
    scale = 1.0
    longest = max(w0, h0)
    if max_side and longest > max_side:
        scale = max_side / float(longest)
        small = img.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))),
                           Image.LANCZOS)
        small_path = f'{path}.small.png'
        small.save(small_path)
        path = small_path

    result, _ = _get_engine()(path)
    items = []
    for box, text, score in (result or []):
        xs = [p[0] / scale for p in box]
        ys = [p[1] / scale for p in box]
        items.append((text.strip(), int(sum(xs) / 4), int(sum(ys) / 4), float(score)))
    return items


def read_texts(d, path=None):
    """截屏并 OCR，返回 [(文字, 中心x, 中心y, 置信度), ...]。"""
    if not available():
        return []
    return read_image(screenshot(d, path))


def locate(d, targets, contains=False):
    """在屏幕上找目标文字，返回 {目标: (x, y)}（设备坐标）。"""
    if isinstance(targets, str):
        targets = [targets]
    items = read_texts(d)
    found = {}
    for target in targets:
        for text, x, y, _score in items:
            if (target in text) if contains else (text == target):
                found[target] = (x, y)
                break
    return found
