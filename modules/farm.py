"""芭芭农场（淘宝）自动化。

流程：
1. 淘宝首页搜索「芭芭农场」-> 点搜索框下方卡片右上「进入」
2. 活动页可能有推广弹窗 / 滑块验证，先清掉直到真正进主界面
3. 点右侧「点击领取」领每日赠送肥料
4. 点底栏「集肥料」展开「做任务赚肥料」面板（canvas 按钮，用 OCR 定位）
5. 逐个执行浏览类任务；跳转支付宝/蚂蚁森林的任务一律跳过
"""
import logging
import time

from modules import activity, captcha, ocr, ui
from modules.utils import mute, open_taobao_search

logger = logging.getLogger(__name__)

KEYWORD = '芭芭农场'

# 农场任务面板的按钮文案
FARM_BTNS = ('去完成', '去签到', '去答题', '去逛逛', '去开启')

# 需要跳过（跳转支付宝/外部 App）的任务
SKIP_KEYWORDS = ('支付宝', '蚂蚁森林', '前往支付', '安装桌面')

BROWSE_SECONDS = {'15': 20, '5': 10}

# 只有图标关闭键的活动弹窗，用文案识别后按返回关闭
POPUP_TEXTS = ('继续施肥', '取消订阅', '明日7点后记得来领', '立即收下',
               '开心收下', '今日施肥越多')
MAX_ROUNDS = 40

# 以下按钮画在 canvas 上，无障碍树里拿不到，用比例/OCR 兜底
ENTER_RATIO = (0.895, 0.176)       # 搜索结果卡片右上「进入」
CARD_ICON_RATIO = (0.12, 0.235)    # 卡片第一个图标「马上施肥」
COLLECT_RATIO = (0.75, 0.75)       # 底栏「集肥料」
CLAIM_RATIO = (0.93, 0.60)         # 右侧「点击领取」


FARM_MARKERS = ('再施肥', '免费领水果', '，肥料，', '品种')


def _on_farm(d):
    """是否已在芭芭农场主界面。

    注意「芭芭农场领红包」「农场领红包 | 下单得肥料」是另一个营销页，
    标题里同样带「芭芭农场」，不能当成主界面。
    """
    act = (d.app_current() or {}).get('activity') or ''
    if 'TMSActivity' not in act:
        return False
    labels = [(n['text'] or n['desc']) for n in ui.dump_nodes(d)]
    if any('领红包' in x for x in labels):
        return False
    return any(any(m in x for m in FARM_MARKERS) for x in labels)


def _back_to_search(d, attempts=3):
    """从子页面退回到搜索结果页。"""
    for _ in range(attempts):
        act = (d.app_current() or {}).get('activity') or ''
        if 'SearchActivity' in act:
            return True
        d.go_back()
        time.sleep(2.5)
    return 'SearchActivity' in ((d.app_current() or {}).get('activity') or '')


def _panel_open(nodes):
    labels = [(n['text'] or n['desc']) for n in nodes]
    if any('肥料明细' in x for x in labels):
        return True
    return sum(1 for n in nodes if n['text'] in FARM_BTNS) >= 2


def open_farm(d):
    """搜索并进入芭芭农场，返回是否成功。

    直接点卡片第一个图标「马上施肥」进农场：
    「进入」经常落到「农场领红包」营销页，还要退回来再点图标，白白多两步。
    """
    logger.info('搜索并进入芭芭农场')
    open_taobao_search(d, KEYWORD)
    time.sleep(3)

    w, h = d.display_size

    # 1) 直达：卡片图标「马上施肥」
    d.click(int(w * CARD_ICON_RATIO[0]), int(h * CARD_ICON_RATIO[1]))
    time.sleep(7)
    clear_popups(d)
    if _on_farm(d):
        return True

    # 2) 兜底：卡片右上「进入」
    logger.info('「马上施肥」未进入农场，改用卡片右上「进入」')
    if _back_to_search(d):
        d.click(int(w * ENTER_RATIO[0]), int(h * ENTER_RATIO[1]))
        time.sleep(7)
        clear_popups(d)
        if _on_farm(d):
            return True

    logger.warning('未能进入芭芭农场主界面')
    return False


def clear_popups(d, rounds=4):
    """清掉推广弹窗 / 施肥提醒 / 滑块验证，直到能正常操作。"""
    for _ in range(rounds):
        act = (d.app_current() or {}).get('activity') or ''
        if 'Ext2Container' in act:
            logger.warning('触发滑动验证，按返回退出')
            d.go_back()
            time.sleep(2)
            continue

        nodes = ui.dump_nodes(d)
        blob = ' '.join((n['text'] + ' ' + n['desc']) for n in nodes)

        # 淘宝会随机在跳转后弹滑块验证，挡住整页
        if captcha.detected_in(nodes):
            logger.warning('农场页出现滑块验证，尝试自动通过')
            captcha.solve(d)
            continue

        # 这类弹窗只有一个 X 图标，文案识别不到「关闭」，直接按返回
        if any(t in blob for t in POPUP_TEXTS):
            logger.info('检测到活动弹窗，按返回关闭')
            d.go_back()
            time.sleep(1.8)
            continue

        if not activity.close_popups(d, rounds=1):
            return
        time.sleep(1)


def claim_daily(d):
    """领右侧「点击领取」的每日赠送肥料。"""
    for n in ui.dump_nodes(d):
        label = n['text'] or n['desc']
        if not n['clickable'] or not label or '肥料' not in label:
            continue
        if '领' not in label:
            continue
        if '明日' in label or '已领' in label:
            logger.info('今日肥料已领过：%s', label)
            return False
        logger.info('领取每日肥料：%s', label)
        ui.tap_node(d, n)
        time.sleep(2.5)
        return True

    hit = ocr.locate(d, '点击领取')
    if '点击领取' in hit:
        x, y = hit['点击领取']
        logger.info('OCR 定位「点击领取」(%d,%d)', x, y)
        d.click(x, y)
        time.sleep(2.5)
        return True

    # 没识别到就不盲点，避免点开别的浮层挡住后面的「集肥料」
    logger.info('未找到「点击领取」按钮，跳过领取每日肥料')
    return False


def open_collect(d):
    """点底栏「集肥料」打开任务面板，返回面板节点。"""
    # 先确认还在农场页，否则点底栏只会点到别的东西
    if not _on_farm(d):
        for _ in range(3):
            d.go_back()
            time.sleep(2)
            if _on_farm(d):
                break
        else:
            logger.warning('不在农场页，重新进入一次')
            if not open_farm(d):
                return None

    # 页面上可能有「明日7点后来领」这类弹窗挡住底栏，先清掉
    clear_popups(d)

    # 农场页有入场动画，页面没稳定时点击会落空，先等一下
    time.sleep(2.5)
    nodes = ui.dump_nodes(d)
    if _panel_open(nodes):
        return nodes
    logger.debug('当前页面节点 %d 个，准备点集肥料', len(nodes))

    hit = ocr.locate(d, '集肥料')
    if '集肥料' in hit:
        x, y = hit['集肥料']
        logger.info('OCR 定位「集肥料」(%d,%d)', x, y)
        d.click(x, y)
        time.sleep(4)
        nodes = ui.dump_nodes(d)
        if _panel_open(nodes):
            return nodes

    # 底栏是固定定位的 canvas，按比例点；没打开就小范围偏移重试（自动校准）
    w, h = d.display_size
    base_x, base_y = COLLECT_RATIO
    for dx, dy in ((0, 0), (0.02, 0), (-0.02, 0), (0, 0.02), (0, -0.02)):
        x, y = int(w * (base_x + dx)), int(h * (base_y + dy))
        logger.info('按比例点「集肥料」(%d,%d)', x, y)
        d.click(x, y)
        time.sleep(3.5)
        nodes = ui.dump_nodes(d)
        if _panel_open(nodes):
            return nodes
    return None


def _browse_wait(desc):
    for key, seconds in BROWSE_SECONDS.items():
        if key in desc:
            return seconds
    return 20


def _scroll_panel(d):
    """在任务面板内向下滑一屏（面板下方还藏着任务）。"""
    w, h = d.display_size
    try:
        d.swipe(int(w * 0.5), int(h * 0.78), int(w * 0.5), int(h * 0.45), duration=0.45)
    except Exception as e:
        logger.warning('面板滑动失败（忽略）: %s', e)
        return False
    time.sleep(1.5)
    return True


def _panel_to_top(d, times=3):
    w, h = d.display_size
    for _ in range(times):
        try:
            d.swipe(int(w * 0.5), int(h * 0.45), int(w * 0.5), int(h * 0.80), duration=0.45)
        except Exception:
            return
        time.sleep(1.2)


# 可自动完成的动作关键词：浏览15秒 / 逛15秒 / 看直播 / 观看
BROWSE_WORDS = ('浏览', '逛', '看直播', '观看', '逛逛')


def _pick_browse(tasks, attempts, external=(), screen_h=0):
    for t in tasks:
        label = t['name'] + t['desc']
        if any(k in label for k in SKIP_KEYWORDS):
            continue
        if t['name'] in external:
            continue
        if t['btn'] != '去完成':
            continue
        if not any(w in label for w in BROWSE_WORDS):
            continue
        if screen_h and not (0 < t['y'] < screen_h * 0.98):
            continue  # 已经滚出屏幕的旧节点，别点
        if attempts.get(t['name'], 0) >= 2:
            continue
        return t
    return None


def _ocr_panel_tasks(d):
    """用 OCR 读面板上可见的任务行。

    这个面板是 canvas 渲染，滚动后无障碍树不会刷新（实测 vivo 上完全滞后），
    所以滚动找任务必须靠 OCR 读屏。
    """
    items = ocr.read_texts(d)
    if not items:
        return []
    btn_labels = ('去完成', '去领取', '去邀请', '去逛逛', '去签到', '去开启')
    btns = [it for it in items if it[0] in btn_labels]

    def is_junk(text):
        t = text.strip()
        return (not t) or t[0] in '+＋' or t.replace('+', '').isdigit()

    tasks = []
    for text, bx, by, _score in btns:
        # 任务名在整行最左侧（右侧紧挨按钮的是 +600 这类奖励数字）
        left = [it for it in items
                if it[1] < bx - 60 and abs(it[2] - by) <= 55
                and not is_junk(it[0]) and len(it[0]) >= 4]
        # 标题在按钮中心上方，下面那行是「逛15秒得」这类描述
        above = [it for it in left if it[2] <= by]
        pool = above or left
        name = min(pool, key=lambda it: (it[1], it[2]))[0] if pool else ''

        below = [it for it in items
                 if it[1] < bx - 60 and 20 < it[2] - by <= 80 and not is_junk(it[0])]
        desc = min(below, key=lambda it: it[2])[0] if below else ''

        tasks.append({'name': name, 'desc': desc, 'btn': text,
                      'x': bx, 'y': by, 'node': None})
    tasks.sort(key=lambda t: t['y'])
    return tasks


def _tap_task(d, task):
    if task.get('node') is not None:
        ui.tap_node(d, task['node'])
    else:
        d.click(task['x'], task['y'])


def run_tasks(d):
    """在「做任务赚肥料」面板里逐个执行任务，返回完成数。"""
    done = 0
    signed = False
    attempts = {}
    external = set()  # 实测会跳转外部 App 的任务名，后续直接跳过
    for round_no in range(1, MAX_ROUNDS + 1):
        nodes = open_collect(d)
        if not nodes:
            logger.warning('集肥料面板没打开')
            break

        h = d.display_size[1]
        use_ocr = ocr.available()

        def read_tasks():
            if use_ocr:
                return _ocr_panel_tasks(d)
            return ui.parse_tasks(ui.dump_nodes(d), FARM_BTNS)

        tasks = read_tasks()
        logger.info('第 %d 轮：面板任务 %d 个（%s）', round_no, len(tasks),
                    'OCR' if use_ocr else 'a11y')
        for t in tasks:
            logger.debug('  · %s | %s | %s', t['name'], t['desc'], t['btn'])

        # 每日签到只点一次
        if not signed:
            sign = next((t for t in tasks if t['btn'] == '去签到'), None)
            if sign:
                logger.info('点击「去签到」')
                _tap_task(d, sign)
                signed = True
                time.sleep(3)
                continue

        task = _pick_browse(tasks, attempts, external, h)

        # 当前屏没有就往下滑着找（面板下方还藏着任务）
        names = {t['name'] for t in tasks}
        for _ in range(3):
            if task:
                break
            logger.info('当前屏没有可做的任务，向下滑动查找')
            if not _scroll_panel(d):
                break
            time.sleep(0.8)
            tasks = read_tasks()
            new_names = {t['name'] for t in tasks}
            if new_names == names:
                if not use_ocr:
                    # 面板是 canvas，滚动后无障碍树可能不刷新，坐标不可信就别点
                    logger.info('滚动后任务列表没变化（无障碍树未刷新），停止下滑')
                    break
                continue
            names = new_names
            task = _pick_browse(tasks, attempts, external, h)

        if not task:
            # 回到顶部再确认一次，避免滑到底后错过上面新刷出的任务
            _panel_to_top(d)
            tasks = read_tasks()
            task = _pick_browse(tasks, attempts, external, h)

        if not task:
            logger.info('没有可自动完成的浏览任务了')
            break

        logger.info('执行任务：%s（%s）', task['name'], task['desc'])
        attempts[task['name']] = attempts.get(task['name'], 0) + 1
        _tap_task(d, task)
        time.sleep(2.5)

        # 有些任务名字里不带「支付宝」，点下去却会拉起支付宝，直接拉黑
        pkg = (d.app_current() or {}).get('package') or ''
        if pkg and pkg != ui.TAOBAO_PKG:
            logger.warning('任务「%s」跳转外部 App（%s），加入跳过名单', task['name'], pkg)
            external.add(task['name'])
            activity.ensure_taobao(d)
            time.sleep(2)
            continue

        # 搜索类任务：先点「搜索发现」里的卡片进商品页，否则不计时
        if '搜一搜' in task['name'] or '搜索' in task['name']:
            page = activity.wait_search_page(d, timeout=8)
            if page:
                activity.open_search_card(d, page)
                time.sleep(2)

        activity.browse_page(d, _browse_wait(task['desc']))

        d.go_back()
        time.sleep(2.5)
        if not _on_farm(d):
            logger.info('返回后不在农场页，再退一次')
            d.go_back()
            time.sleep(2)
        done += 1

    return done


def run(d, mode='auto', keyword=KEYWORD):
    """执行芭芭农场任务，返回结果摘要。"""
    logger.info('开始运行芭芭农场任务')
    activity.prepare_device(d)
    mute(d)

    if mode == 'manual':
        input('请手动进入芭芭农场页面，完成后按回车继续...')
        if not _on_farm(d):
            raise RuntimeError('未检测到芭芭农场页面')
    elif not open_farm(d):
        raise RuntimeError('未能进入芭芭农场，请检查网络或页面是否改版')

    clear_popups(d)

    claimed = False
    try:
        claimed = claim_daily(d)
    except Exception as e:
        logger.warning('领取每日肥料失败: %s', e)

    done = run_tasks(d)
    logger.info('芭芭农场执行完毕：完成任务 %d 个，今日肥料%s', done, '已领取' if claimed else '未领取')
    return f'{done}个任务/{"已领" if claimed else "无"}每日肥料'
