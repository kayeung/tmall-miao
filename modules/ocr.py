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


def read_texts(d, path=None):
    """截屏并 OCR，返回 [(文字, 中心x, 中心y, 置信度), ...]。"""
    if not available():
        return []
    path = screenshot(d, path)
    engine = _get_engine()
    result, _ = engine(path)
    items = []
    for box, text, score in (result or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append((text.strip(), int(sum(xs) / 4), int(sum(ys) / 4), float(score)))
    return items


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
