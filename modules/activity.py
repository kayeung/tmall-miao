"""淘金币双11活动页的通用操作。

金币任务和能量任务共用同一套「进活动 -> 找入口 -> 打开任务面板 -> 返回」逻辑，
差异只有入口按钮、面板标题和任务解析方式。
"""
import logging
import re
import time

from modules import ui
from modules.utils import human_swipe, open_taobao_search

logger = logging.getLogger(__name__)

# 活动搜索关键词
KEYWORD = '淘金币双11狂享20亿'

# 活动页底部两个入口按钮的相对坐标（H5 按视口等比缩放，所以用比例）
COIN_ENTRY = (0.10, 0.396)
ENERGY_ENTRY = (0.896, 0.396)

# 两个面板的标题
COIN_PANEL = ('赚金币抵钱',)
ENERGY_PANEL = ('做任务赚能量',)


def _activity_markers(nodes):
    """活动页判定：H5 容器 id 或页面标题文案（避免用'淘金币'三字，搜索结果页也会命中）。"""
    for n in nodes:
        if n['rid'] in ('eva-canvas', 'ice-container'):
            return True
        if n['text'] == '淘金币首页':
            return True
    return False


def wait_activity(d, timeout=40):
    """等待活动页加载完成；兜底用宿主容器 Activity 判定。"""
    nodes = ui.wait_for(d, _activity_markers, timeout=timeout, desc='活动页')
    if nodes:
        return nodes
    activity = (d.app_current() or {}).get('activity', '')
    if 'themis' in activity.lower():
        logger.info('通过宿主容器识别活动页：%s', activity)
        return ui.dump_nodes(d)
    return None


def on_activity(d, tries=2):
    """是否停留在活动页（带重试，避免 H5 重绘瞬间的空层级误判）。"""
    for _ in range(tries):
        panel, nodes = ui.inspect(d)
        if panel or _activity_markers(nodes):
            return True
        time.sleep(0.6)
    return False


# 会被任务拉起、且首启会弹隐私弹窗挡住自动化的 App
BLOCK_APPS = ('com.eg.android.AlipayGphone', 'com.ss.android.article.lite')


def ensure_taobao(d):
    """确保前台是淘宝。

    有些任务会拉起支付宝（首次会弹隐私弹窗），弹窗会挡住所有点击。
    这里只把淘宝切回前台；如果外部 App 卡在返回栈里反复抢焦点，就把它强制停掉
    （不点它的任何弹窗，避免替用户做授权）。
    """
    pkg = (d.app_current() or {}).get('package', '')
    if pkg == ui.TAOBAO_PKG:
        return True

    logger.warning('当前前台不是淘宝（%s），切回淘宝', pkg or '未知')
    d.start_app(ui.TAOBAO_PKG)
    time.sleep(4)
    if (d.app_current() or {}).get('package') == ui.TAOBAO_PKG:
        return True

    if pkg in BLOCK_APPS:
        logger.warning('强制停止阻挡的 App: %s', pkg)
        try:
            d.shell(['am', 'force-stop', pkg])
        except Exception as e:
            logger.warning('强制停止失败: %s', e)
        time.sleep(1.5)
        d.start_app(ui.TAOBAO_PKG)
        time.sleep(4)

    ok = (d.app_current() or {}).get('package') == ui.TAOBAO_PKG
    if not ok:
        logger.warning('切换淘宝失败，当前仍是 %s', (d.app_current() or {}).get('package'))
    return ok


def scroll_top(d):
    """把活动页滚回顶部（仅在入口按钮找不到时用）。"""
    _gentle_scroll_top(d)


def open_activity(d, keyword=KEYWORD):
    """搜索关键词进入活动页。"""
    logger.info('打开淘宝并搜索活动：%s', keyword)
    open_taobao_search(d, keyword)
    logger.info('等待活动页加载...')
    if not wait_activity(d):
        raise RuntimeError('未检测到活动页，请确认淘宝已登录、活动可正常进入')
    logger.info('活动页已打开')
    time.sleep(2)


def enter_activity(d, mode='auto', keyword=KEYWORD):
    """按模式进入活动页（auto=自动搜索，manual=人工进入，适用于淘宝分身）。"""
    if mode == 'manual':
        input('请手动打开淘宝并进入活动页面，完成后按回车继续...')
        if not wait_activity(d, timeout=15):
            raise RuntimeError('未检测到活动页，请确认已进入活动页面')
        return
    open_activity(d, keyword)


def _banner_mid(d):
    """从截图里找「升级赛车拿钱」黄色横幅的中心 y，用来定位两个入口按钮。

    活动页是 canvas 渲染，无障碍树里没有入口文案，只能靠像素；
    比例写死会在页面小幅改版时点空，所以优先按实际横幅位置算。
    """
    try:
        import os
        import tempfile

        from PIL import Image
        path = os.path.join(tempfile.gettempdir(), 'tmall_entry_shot.png')
        d.device.screenshot(path)
        img = Image.open(path).convert('RGB')
        w, h = img.size
        px = img.load()
        rows = []
        for y in range(int(h * 0.20), int(h * 0.60), 2):
            hits = 0
            for x in range(0, w, 6):
                r, g, b = px[x, y]
                if r > 200 and g > 160 and b < 110:
                    hits += 1
            if hits > (w / 6) / 3:
                rows.append(y)
        if rows:
            return (min(rows) + max(rows)) // 2
    except Exception as e:
        logger.debug('横幅识别失败: %s', e)
    return None


def _gentle_scroll_top(d, times=3):
    """轻微上滚（内容下移），触发下降刷新也没关系，最多试几次。"""
    w, h = d.display_size
    for _ in range(times):
        try:
            d.swipe(int(w * 0.5), int(h * 0.30), int(w * 0.5), int(h * 0.62), duration=0.4)
        except Exception as e:
            logger.warning('回顶部滑动失败（忽略）: %s', e)
            return
        time.sleep(0.8)
        if _banner_mid(d) is not None:
            return


def tap_entry(d, ratio, label):
    """点击活动页底部的入口按钮（去赚金币 / 去赚能量）。"""
    nodes = ui.dump_nodes(d)
    if ui.tap_text(d, nodes, label, exact=False):
        logger.debug('通过文案点击「%s」', label)
        return True

    w, h = d.display_size
    y = _banner_mid(d)
    if y is None:
        # 横幅看不到，先把页面滚回顶部再找一次
        _gentle_scroll_top(d)
        y = _banner_mid(d) or int(h * ratio[1])

    x = int(w * ratio[0])
    logger.debug('通过坐标点击「%s」(%d,%d)', label, x, y)
    d.click(x, y)
    return True


def back_to_activity(d, attempts=3):
    """连续返回到活动页，防止停留在任务打开的商品页/搜索页。"""
    ensure_taobao(d)
    for i in range(attempts):
        if on_activity(d):
            return True
        logger.info('当前不在活动页，返回上一级 (%d/%d)', i + 1, attempts)
        d.go_back()
        time.sleep(2)
    if on_activity(d):
        return True
    logger.warning('多次返回后仍未回到活动页')
    return False


def ensure_panel(d, titles, ratio, label, attempts=3):
    """确保指定任务面板处于打开状态，返回面板内的节点列表。

    第一次只做「退回活动页 + 点入口」，失败后直接重启淘宝重新进入活动，
    这样页面一定在顶部，坐标点击才不会落偏。
    """
    for i in range(attempts):
        ensure_taobao(d)
        nodes = ui.dump_panel(d, titles)
        if nodes:
            return nodes

        try:
            if i == 0:
                if not on_activity(d) and not back_to_activity(d):
                    logger.info('不在活动页，重新搜索进入')
                    open_activity(d)
                else:
                    logger.info('任务面板未打开，点击「%s」', label)
                    tap_entry(d, ratio, label)
            else:
                logger.info('任务面板仍未打开，重新进入活动页（第%d次）', i + 1)
                open_activity(d)
        except Exception as e:
            logger.warning('打开任务面板失败: %s', e)
            return None

        nodes = ui.wait_for(d, lambda ns: bool(ns), timeout=8, desc='任务面板',
                            dump=lambda dd: ui.dump_panel(dd, titles))
        if nodes:
            logger.info('任务面板已打开')
            return nodes
    return None


def scroll_panel(d, direction='up'):
    """在任务面板内部滚动一屏（面板是弹层，滚动它自己的列表）。"""
    w, h = d.display_size
    x = int(w * 0.5)
    if direction == 'up':
        y1, y2 = int(h * 0.80), int(h * 0.55)
    else:
        y1, y2 = int(h * 0.55), int(h * 0.80)
    try:
        d.swipe(x, y1, x, y2, duration=0.3)
    except Exception as e:
        logger.warning('面板滑动失败（忽略）: %s', e)
        return False
    time.sleep(1.2)
    return True


def panel_to_top(d, times=3):
    """把面板滚回顶部。"""
    for _ in range(times):
        if not scroll_panel(d, 'down'):
            return


def close_panel(d):
    """关闭任务面板（点右上角关闭，兜底用返回键）。"""
    nodes = ui.dump_nodes(d)
    for n in nodes:
        if n['text'] == '关闭' and n['clickable']:
            ui.tap_node(d, n)
            time.sleep(1.2)
            return True
    d.go_back()
    time.sleep(1.2)
    return False


def browse_page(d, seconds):
    """任务页停留指定秒数。

    部分任务的倒计时只有滑动 feed 才推进，所以在 H5 页面上持续小幅上下滑动；
    商品详情页（NewDetailActivity/TTDetailActivity）会自动播放，不滑动以免误触。
    """
    w, h = d.display_size
    x = int(w * 0.5)
    y1, y2 = int(h * 0.75), int(h * 0.45)
    deadline = time.time() + seconds
    swipes = 0
    while time.time() < deadline:
        current = d.app_current() or {}
        if current.get('package') != ui.TAOBAO_PKG:
            logger.warning('任务页跳到了其他应用（%s），切回淘宝', current.get('package'))
            ensure_taobao(d)
            return False
        if 'detail' in (current.get('activity') or '').lower():
            time.sleep(1.5)
            continue
        try:
            # 拟人滑动轨迹（带波形抖动），比直线 swipe 更接近真人浏览
            human_swipe(d, x, y1, x, y2, wave_range=16)
            swipes += 1
        except Exception as e:
            logger.warning('浏览滑动失败（忽略）: %s', e)
        time.sleep(1.2)
    logger.debug('浏览页面共滑动 %d 次', swipes)
    return True


def _is_search_page(nodes):
    texts = {n['text'] for n in nodes}
    return '搜索发现' in texts or '搜索有福利' in texts


def tap_first_recommendation(d, nodes):
    """搜索类任务：点「搜索发现」下面的第一个推荐词，进商品列表。"""
    anchor = ui.find_nodes(nodes, text='搜索发现')
    if not anchor:
        return False
    a = anchor[0]
    cands = [n for n in nodes
             if n['clickable'] and n['t'] >= a['b'] and n['l'] < a['r'] and n['text']]
    if not cands:
        return False
    item = min(cands, key=lambda n: (n['t'], n['l']))
    logger.info('点击推荐词：%s', item['text'].split()[0])
    ui.tap_node(d, item)
    return True


def run_browse_task(d, node, seconds):
    """执行一次浏览任务：点按钮 -> (搜索类先点推荐词) -> 滑动浏览 -> 返回活动页。"""
    ui.tap_node(d, node)
    time.sleep(2.5)

    nodes = ui.dump_nodes(d)
    if _is_search_page(nodes):
        if tap_first_recommendation(d, nodes):
            time.sleep(3)

    browse_page(d, seconds)

    d.go_back()
    time.sleep(2)
    if not on_activity(d, tries=1):
        logger.info('返回后不在活动页，再退一次')
        d.go_back()
        time.sleep(2)
        if not on_activity(d, tries=2):
            logger.warning('仍未回到活动页，重新搜索进入')
            open_activity(d)
    logger.info('已返回活动页')


def find_task(d, titles, parse_fn, picker, max_screens=3):
    """在当前面板里找可执行任务，必要时滚动面板（屏幕外还有任务）。

    返回 (task, 该屏节点)；找不到返回 (None, 最后一次的节点)。
    """
    nodes = ui.dump_panel(d, titles)
    if not nodes:
        return None, None

    names = None
    for _ in range(max_screens):
        tasks = parse_fn(nodes)
        task = picker(tasks)
        if task:
            return task, nodes

        cur = {t['name'] for t in tasks}
        if names is not None and cur == names:
            return None, nodes  # 滚动后没变化，说明到底了
        names = cur

        if not scroll_panel(d):
            return None, nodes
        nodes = ui.dump_panel(d, titles) or []
    return None, nodes


def find_task_all(d, titles, parse_fn, picker):
    """先在面板当前位置扫描，找不到再回到顶部扫一遍（覆盖上下两侧屏幕外任务）。"""
    task, nodes = find_task(d, titles, parse_fn, picker)
    if task:
        return task, nodes
    panel_to_top(d)
    return find_task(d, titles, parse_fn, picker)


def progress(nodes, label='完成进度'):
    """读取面板进度。

    金币面板是单个节点「完成进度 12/20」；
    能量面板是「当前进度」+「3/50」两个节点，所以两种都兼容。
    """
    m = re.search(r'(\d+)\s*/\s*\d+', ui.text_of(nodes, label))
    if m:
        return int(m.group(1))

    labels = ui.find_nodes(nodes, text=label)
    if not labels:
        return 0
    lab = labels[0]
    nums = [n for n in nodes
            if re.fullmatch(r'\d+\s*/\s*\d+', n['text'])
            and n['t'] >= lab['t'] - 10
            and abs(ui.center(n)[0] - ui.center(lab)[0]) < 220]
    if not nums:
        return 0
    return int(min(nums, key=lambda n: n['t'])['text'].split('/')[0].strip())
