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

from modules import activity, ocr, ui
from modules.utils import mute, open_taobao_search

logger = logging.getLogger(__name__)

KEYWORD = '芭芭农场'

# 农场任务面板的按钮文案
FARM_BTNS = ('去完成', '去签到', '去答题', '去逛逛', '去开启')

# 需要跳过（跳转支付宝/外部 App）的任务
SKIP_KEYWORDS = ('支付宝', '蚂蚁森林', '前往支付', '安装桌面')

BROWSE_SECONDS = {'15': 20, '5': 10}
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
    """搜索并进入芭芭农场，返回是否成功。"""
    logger.info('搜索并进入芭芭农场')
    open_taobao_search(d, KEYWORD)
    time.sleep(3)

    w, h = d.display_size

    # 1) 卡片右上「进入」
    d.click(int(w * ENTER_RATIO[0]), int(h * ENTER_RATIO[1]))
    time.sleep(7)
    clear_popups(d)
    if _on_farm(d):
        return True

    # 2) 「进入」常落到「农场领红包」子页，退回搜索页点卡片图标「马上施肥」
    logger.info('「进入」未到主界面，改为点卡片图标「马上施肥」')
    if _back_to_search(d):
        d.click(int(w * CARD_ICON_RATIO[0]), int(h * CARD_ICON_RATIO[1]))
        time.sleep(8)
        clear_popups(d)
        if _on_farm(d):
            return True

    logger.warning('未能进入芭芭农场主界面')
    return False


def clear_popups(d, rounds=4):
    """清掉推广弹窗 / 滑块验证，直到能正常操作。"""
    for _ in range(rounds):
        act = (d.app_current() or {}).get('activity') or ''
        if 'Ext2Container' in act:
            logger.warning('触发滑动验证，按返回退出')
            d.go_back()
            time.sleep(2)
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


def run_tasks(d):
    """在「做任务赚肥料」面板里逐个执行任务，返回完成数。"""
    done = 0
    signed = False
    for round_no in range(1, MAX_ROUNDS + 1):
        nodes = open_collect(d)
        if not nodes:
            logger.warning('集肥料面板没打开')
            break

        tasks = ui.parse_tasks(nodes, FARM_BTNS)
        logger.info('第 %d 轮：面板任务 %d 个', round_no, len(tasks))
        for t in tasks:
            logger.debug('  · %s | %s | %s', t['name'], t['desc'], t['btn'])

        # 每日签到只点一次
        if not signed:
            sign = next((t for t in tasks if t['btn'] == '去签到'), None)
            if sign:
                logger.info('点击「去签到」')
                ui.tap_node(d, sign['node'])
                signed = True
                time.sleep(3)
                continue

        task = None
        for t in tasks:
            label = t['name'] + t['desc']
            if any(k in label for k in SKIP_KEYWORDS):
                logger.debug('跳转外部 App 的任务，跳过：%s', t['name'])
                continue
            if t['btn'] == '去完成' and ('浏览' in t['desc'] or '浏览' in t['name']):
                task = t
                break

        if not task:
            logger.info('没有可自动完成的浏览任务了')
            break

        logger.info('执行任务：%s（%s）', task['name'], task['desc'])
        ui.tap_node(d, task['node'])
        time.sleep(2.5)

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
