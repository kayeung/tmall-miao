"""淘金币双11活动页的通用操作。

金币任务和能量任务共用同一套「进活动 -> 找入口 -> 打开任务面板 -> 返回」逻辑，
差异只有入口按钮、面板标题和任务解析方式。
"""
import logging
import re
import time

from modules import ui
from modules.utils import human_swipe, open_taobao_search, search_in_taobao

logger = logging.getLogger(__name__)

# 活动搜索关键词
KEYWORD = '淘金币双11狂享20亿'

# 活动页底部两个入口按钮的相对坐标（H5 按视口等比缩放，所以用比例）
COIN_ENTRY = (0.10, 0.396)
ENERGY_ENTRY = (0.896, 0.396)

# 两个面板的标题（金币面板有旧版「赚金币抵钱」和新版「今日速赚淘金币」两套）
COIN_PANEL = ('赚金币抵钱', '完成下方任务得额外金币', '更多金币等你赚')
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
BLOCK_APPS = ('com.eg.android.AlipayGphone', 'com.ss.android.article.lite',
              'com.vivo.appfilter')


def ensure_taobao(d):
    """确保前台是淘宝。

    有些任务会拉起支付宝（首次会弹隐私弹窗），弹窗会挡住所有点击。
    这里只把淘宝切回前台；如果外部 App 卡在返回栈里反复抢焦点，就把它强制停掉
    （不点它的任何弹窗，避免替用户做授权）。
    """
    ensure_unlocked(d)

    pkg = (d.app_current() or {}).get('package', '')
    if pkg == ui.TAOBAO_PKG:
        return True

    logger.warning('当前前台不是淘宝（%s），切回淘宝', pkg or '未知')
    d.start_app(ui.TAOBAO_PKG, user=ui.TAOBAO_USER)
    if _wait_taobao(d, 25):
        return True

    if pkg in BLOCK_APPS:
        logger.warning('强制停止阻挡的 App: %s', pkg)
        try:
            d.shell(['am', 'force-stop', pkg])
        except Exception as e:
            logger.warning('强制停止失败: %s', e)
        time.sleep(1.5)
        d.start_app(ui.TAOBAO_PKG, user=ui.TAOBAO_USER)
        if _wait_taobao(d, 25):
            return True

    logger.warning('切换淘宝失败，当前仍是 %s', (d.app_current() or {}).get('package'))
    return False


def _wait_taobao(d, timeout=25):
    """等待淘宝到前台；期间处理 vivo/OPPO 的「应用分身」选择框。"""
    for _ in range(timeout):
        cur = d.app_current() or {}
        if cur.get('package') == ui.TAOBAO_PKG:
            return True
        if ui.is_clone_resolver(d):
            ui.tap_app_instance(d, clone=ui.TAOBAO_IS_CLONE)
            time.sleep(2)
            continue
        time.sleep(1)
    return False


def scroll_top(d):
    """把活动页滚回顶部（仅在入口按钮找不到时用）。"""
    _gentle_scroll_top(d)


def open_activity(d, keyword=KEYWORD):
    """搜索关键词进入活动页。"""
    logger.info('打开淘宝并搜索活动：%s', keyword)
    ensure_unlocked(d)
    for attempt in range(2):
        try:
            open_taobao_search(d, keyword)
            break
        except Exception as e:
            if attempt == 1:
                raise
            logger.warning('打开淘宝/搜索失败（%s），重试一次', e)
            time.sleep(3)
    logger.info('等待活动页加载...')
    if not wait_activity(d):
        raise RuntimeError('未检测到活动页，请确认淘宝已登录、活动可正常进入')
    logger.info('活动页已打开')
    time.sleep(2)


def reenter_activity(d, keyword=KEYWORD):
    """重新进入活动页：优先在 App 内返回首页再搜索，尽量不杀进程回桌面。

    杀进程重启在 vivo/OPPO 上会触发「应用分身」选择框，容易打断流程。
    """
    if (d.app_current() or {}).get('package') == ui.TAOBAO_PKG:
        try:
            if search_in_taobao(d, keyword) and wait_activity(d, timeout=40):
                logger.info('已在 App 内重新进入活动页')
                return True
        except Exception as e:
            logger.warning('App 内重新搜索失败: %s', e)

    logger.info('App 内无法恢复，重启淘宝进入活动页')
    open_activity(d, keyword)
    return bool(wait_activity(d, timeout=20))


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


# 弹窗/引导层上的关闭类文案
CLOSE_TEXTS = ('关闭', '×', 'X', 'x', '跳过', '我知道了', '知道了', '以后再说',
               '暂不', '取消', '不再提示', '放弃', '下次再说')


def close_popups(d, rounds=3):
    """关掉活动页上的弹窗/引导层（它们会挡住入口按钮）。返回关闭次数。"""
    closed = 0
    for _ in range(rounds):
        nodes = ui.dump_nodes(d)
        labels = [(n['text'] or n['desc']).strip() for n in nodes]

        # 任务面板自己也有「关闭」，别把面板关掉
        if any(t in labels for t in ui.PANEL_TITLES):
            break

        cands = [n for n in nodes
                 if n['clickable'] and (n['text'] or n['desc']).strip() in CLOSE_TEXTS]
        if not cands:
            break

        cands.sort(key=lambda n: (0 if (n['text'] or n['desc']).strip() == '关闭' else 1, n['t']))
        name = (cands[0]['text'] or cands[0]['desc']).strip()
        logger.info('活动页有弹窗，点击「%s」关闭', name)
        ui.tap_node(d, cands[0])
        closed += 1
        time.sleep(1.5)
    return closed


def tap_entry(d, ratio, label, offset=0):
    """点击活动页底部的入口按钮（去赚金币 / 去赚能量）。

    offset 用于失败重试时小幅上下平移（页面没渲染完时横幅定位可能偏）。
    """
    n = close_popups(d)
    if n:
        logger.info('已关闭 %d 个弹窗', n)

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

    y += int(h * 0.02) * offset
    x = int(w * ratio[0])
    logger.debug('通过坐标点击「%s」(%d,%d)', label, x, y)
    d.click(x, y)
    return True


def wake_screen(d):
    """点亮屏幕（熄屏状态下 App 起不到前台）。"""
    try:
        info = d.device.info or {}
        if not info.get('screenOn', True):
            logger.info('屏幕已熄灭，正在点亮')
            d.device.screen_on()
            time.sleep(1)
    except Exception as e:
        logger.debug('读取屏幕状态失败: %s', e)


# 锁屏界面才会出现的文案
LOCK_HINTS = ('上滑即可解锁', '滑动解锁', '上滑解锁', '双指上滑', '输入密码',
              '绘制图案', '指纹解锁', '面部识别', '重新解锁')


def _is_locked(d, nodes=None):
    """是否处于锁屏界面。

    不能只看有没有「解锁」两个字：活动页/商品页也常有「解锁好礼」这类文案，
    必须同时满足「前台不是淘宝」且「停在各家桌面」才判定为锁屏。
    """
    cur = d.app_current() or {}
    pkg = (cur.get('package') or '').lower()

    nodes = nodes if nodes is not None else ui.dump_nodes(d)
    blob = ' '.join((n['text'] + ' ' + n['desc']) for n in nodes)

    if any(h in blob for h in LOCK_HINTS):
        return True
    if pkg == ui.TAOBAO_PKG:
        return False

    launcher = any(k in pkg for k in ('launcher', 'systemui', 'homepage'))
    return launcher and ('解锁' in blob or '上滑' in blob)


def ensure_unlocked(d, tries=2):
    """保证手机已解锁；无密码时会自动上滑解锁，有密码则明确报错。"""
    wake_screen(d)
    if not _is_locked(d):
        return True

    for i in range(tries):
        logger.warning('手机处于锁屏，尝试解锁（第%d次）', i + 1)
        try:
            d.device.unlock()
        except Exception as e:
            logger.debug('unlock 调用失败: %s', e)
        time.sleep(1.5)
        if not _is_locked(d):
            logger.info('已解锁')
            return True

    raise RuntimeError('手机处于锁屏状态，请先解锁手机（或关闭锁屏密码）后再运行')


def prepare_device(d):
    """运行前的设备准备：常亮 + 解锁。"""
    try:
        # 充电/连接 USB 时不熄屏，避免跑到一半黑屏
        d.shell(['svc', 'power', 'stayon', 'true'])
    except Exception as e:
        logger.debug('设置常亮失败（忽略）: %s', e)
    ensure_unlocked(d)


def _is_taobao_home(nodes):
    """是否停在淘宝首页（有首页搜索栏）。"""
    return any(n['desc'] == '搜索栏' or n['text'] == '搜索栏' for n in nodes)


def back_to_activity(d, attempts=3):
    """连续返回到活动页，防止停留在任务打开的商品页/搜索页。

    注意：如果已经回到淘宝首页或已经退出淘宝，就不能再按返回键了
    （否则会把整个 App 退到桌面），直接返回 False 让调用方重新搜索进入。
    """
    ensure_taobao(d)
    for i in range(attempts):
        panel, nodes = ui.inspect(d)
        if panel or _activity_markers(nodes):
            return True
        if _is_taobao_home(nodes):
            logger.info('已回到淘宝首页，不再按返回键')
            return False
        if (d.app_current() or {}).get('package') != ui.TAOBAO_PKG:
            logger.info('已离开淘宝，停止按返回键')
            return False
        logger.info('当前不在活动页，返回上一级 (%d/%d)', i + 1, attempts)
        d.go_back()
        time.sleep(2)

    panel, nodes = ui.inspect(d)
    if panel or _activity_markers(nodes):
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
            if not on_activity(d) and not back_to_activity(d):
                logger.info('不在活动页，重新搜索进入')
                reenter_activity(d)
            elif i >= attempts - 1:
                logger.info('多次点击仍未打开面板，重新进入活动页（第%d次）', i + 1)
                reenter_activity(d)
            else:
                logger.info('任务面板未打开，点击「%s」（第%d次）', label, i + 1)
                tap_entry(d, ratio, label, offset=i)
        except Exception as e:
            logger.warning('打开任务面板失败: %s', e)
            return None

        nodes = ui.wait_for(d, lambda ns: bool(ns), timeout=10, desc='任务面板',
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
        # 慢一点滑，避免惯性滚动导致后面按坐标点击落空
        d.swipe(x, y1, x, y2, duration=0.45)
    except Exception as e:
        logger.warning('面板滑动失败（忽略）: %s', e)
        return False
    time.sleep(1.6)
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
    tick = 0
    is_detail = False
    while time.time() < deadline:
        # 查前台应用要发 adb 命令，比较慢，每 3 次滑动手势查一次即可
        if tick % 3 == 0:
            current = d.app_current() or {}
            if current.get('package') != ui.TAOBAO_PKG:
                logger.warning('任务页跳到了其他应用（%s），切回淘宝', current.get('package'))
                ensure_taobao(d)
                return False
            is_detail = 'detail' in (current.get('activity') or '').lower()
        tick += 1

        try:
            # 拟人滑动轨迹（带波形抖动），比直线 swipe 更接近真人浏览；
            # 商品详情页也滑，只是间隔长一点，避免频繁手势误触
            human_swipe(d, x, y1, x, y2, wave_range=16, base_speed=0.4)
            swipes += 1
        except Exception as e:
            logger.warning('浏览滑动失败（忽略）: %s', e)
        time.sleep(2.0 if is_detail else 1.2)
    logger.debug('浏览页面共滑动 %d 次', swipes)
    return True


def _label(n):
    """节点上显示的文字：H5 在 text 里，原生控件常常在 content-desc 里。"""
    return n['text'] or n['desc']


def _is_search_page(nodes):
    labels = {_label(n) for n in nodes}
    return '搜索发现' in labels or '搜索有福利' in labels


def wait_search_page(d, timeout=10):
    """搜索类任务点开后页面加载慢，轮询等「搜索发现」出现。"""
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        last = ui.dump_nodes(d)
        if _is_search_page(last):
            return last
        time.sleep(0.8)
    logger.debug('等待搜索页超时，节点数=%d', len(last))
    return None


def _page_signature(nodes):
    return {_label(n) for n in nodes if _label(n)}


def _search_cards(nodes):
    """从当前页面里挑出「搜索发现」下面的商品卡片（按位置从上到下）。"""
    anchor = [n for n in nodes if _label(n) == '搜索发现']
    if not anchor:
        return []
    a = anchor[0]
    cards = []
    for n in nodes:
        label = _label(n)
        if not n['clickable'] or not label:
            continue
        if label in ('搜索发现',) or label.startswith('点击隐藏'):
            continue
        # 标题底边常常比第一排卡片顶边还低几像素，这里留容差
        if n['t'] < a['t'] - 10:
            continue
        width = n['r'] - n['l']
        height = n['b'] - n['t']
        if width < 120 or height < 80:  # 排除小标签/小按钮
            continue
        cards.append(n)
    cards.sort(key=lambda n: (n['t'], n['l']))
    return cards


def open_search_card(d, nodes, tries=2):
    """搜索类任务：点「搜索发现」里的任一卡片，进入商品页。

    卡片可能在屏幕下方，先找当前屏，没有就往下滚一屏再找。
    """
    w, h = d.display_size
    for _ in range(3):
        cards = _search_cards(nodes)
        if cards:
            before = _page_signature(nodes)
            for card in cards[:tries]:
                title = _label(card).split()[0][:16]
                logger.info('点击搜索发现卡片：%s', title)
                ui.tap_node(d, card)
                time.sleep(3.5)
                page = ui.dump_nodes(d)
                if _page_signature(page) != before:
                    return True
                logger.info('页面没变化，换一张卡片')
            return False

        logger.info('当前屏没有搜索发现卡片，向下滚动查找')
        try:
            human_swipe(d, int(w * 0.5), int(h * 0.72), int(w * 0.5), int(h * 0.45), wave_range=14)
        except Exception as e:
            logger.warning('搜索页滑动失败（忽略）: %s', e)
        time.sleep(1.5)
        nodes = ui.dump_nodes(d)
    logger.warning('搜索发现里没找到可点的卡片')
    return False


def _tap_task_button(d, task, titles, parse_fn):
    """点任务按钮；如果点完面板还在，说明点空/点错，重新定位同名任务再点一次。"""
    ui.tap_node(d, task['node'])
    time.sleep(2.5)
    if not titles:
        return True

    panel = ui.dump_panel(d, titles)
    if not panel:
        return True

    logger.warning('点击后仍停留在任务面板，重新定位按钮重试')
    base = task.get('base') or task['name'].split('(')[0]
    again = None
    for t in (parse_fn(panel) if parse_fn else []):
        if (t.get('base') or t['name'].split('(')[0]) == base:
            again = t
            break
    if not again:
        return False

    ui.tap_node(d, again['node'])
    time.sleep(2.5)
    return not ui.dump_panel(d, titles)


def run_browse_task(d, task, seconds, titles=None, parse_fn=None):
    """执行一次浏览任务：点按钮 -> (搜索类先点卡片) -> 滑动浏览 -> 返回任务面板。"""
    name = task.get('name', '')
    is_search = '搜一搜' in name or '搜索' in name

    if not _tap_task_button(d, task, titles, parse_fn):
        logger.warning('任务按钮点击后仍未进入任务页，跳过本次')
        return False

    if is_search:
        # 搜索页偶尔加载较慢，等「搜索发现」出来再点卡片
        nodes = wait_search_page(d, timeout=8) or ui.dump_nodes(d)
        if _is_search_page(nodes):
            if open_search_card(d, nodes):
                time.sleep(2)
        else:
            logger.warning('搜索页未出现「搜索发现」，按普通浏览处理')
    else:
        nodes = ui.dump_nodes(d)
        if _is_search_page(nodes) and open_search_card(d, nodes):
            time.sleep(2)

    browse_page(d, seconds)

    # 先返回一次：H5 搜索页是浮层，一次就能回到面板
    d.go_back()
    time.sleep(2.5)
    if titles and ui.dump_panel(d, titles):
        logger.info('已返回任务面板')
        return True

    # 原生搜索页（SearchActivity）叠了两层，需要再返回一次
    if _is_search_page(ui.dump_nodes(d)):
        logger.info('返回后仍在搜索页，再返回一次')
        d.go_back()
        time.sleep(2.5)
        if titles and ui.dump_panel(d, titles):
            logger.info('已返回任务面板')
            return True

    if not on_activity(d, tries=2):
        logger.warning('仍未回到活动页，重新搜索进入')
        try:
            reenter_activity(d)
        except Exception as e:
            logger.warning('重新进入活动失败: %s', e)
            return False
    logger.info('已返回活动页')
    return True


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
